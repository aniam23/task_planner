from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from lxml import etree
import json
import re
import logging
import time
import uuid
from psycopg2 import OperationalError, InternalError
_logger = logging.getLogger(__name__)

class TaskBoard(models.Model):
    _name = 'task.board'
    _description = 'Task Board'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    # --------------------------------------------
    # BASIC FIELDS
    # --------------------------------------------
    name = fields.Char(string='Grupo', required=True, tracking=True)
    sequence = fields.Integer(string='Sequence', default=10)
    completion_date = fields.Datetime(string='Due Date')
    department_id = fields.Many2one(
    'boards.planner', 
    string='Departamento del Grupo', 
    ondelete='cascade',
    domain="[]"
    )
    hr_department_id = fields.Many2one(
        'hr.department',
        string='Departamento',
        related='department_id.department_id',
        store=True,
        readonly=True
    )

    has_dynamic_fields = fields.Boolean(
        string="Tiene Campos Dinámicos",
        compute='_compute_has_dynamic_fields',
        store=False  # No almacenado, solo computado
    )

    dynamic_field_to_remove = fields.Selection(
        selection='_get_dynamic_field_options',
        string='Campo a eliminar',
        help='Seleccione el campo dinámico que desea eliminar'
    )
    person = fields.Many2one(
        'hr.employee',
        string='Responsable',
        tracking=True,
        required=True,
        domain="[('id', 'in', allowed_member_ids)]"
    )
    allowed_member_ids = fields.Many2many(
        'hr.employee',
        compute='_compute_allowed_members',
        string='Miembros'
    )
    state = fields.Selection([
        ('new', 'New'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('stuck', 'Stuck'),
        ('view_subtasks', 'View Subtasks')
    ], string='Estado', default='new', tracking=True)
    color = fields.Integer(string='Color', compute='_compute_color_from_state', store=True)
    files = fields.Many2many('ir.attachment', string='Agregar Archivos')
    show_subtasks = fields.Boolean(string='Ver tareas', invisible=True)
    # --------------------------------------------
    # SUBTASK RELATED FIELDS
    # --------------------------------------------
    subtask_ids = fields.One2many('subtask.board', 'task_id', string='Tareas', store=True)
    subtasks_count = fields.Integer(string='Numero de Tareas', compute='_compute_progress', store=True)
    completed_subtasks = fields.Integer(string='Tareas Completadas', compute='_compute_progress', store=True)
    total_subtasks = fields.Integer(string='Total de Tareas', compute='_compute_progress', store=True)
    progress = fields.Float(string='Progreso', compute='_compute_progress', store=True, group_operator="avg")
    # --------------------------------------------
    # DYNAMIC FIELDS CONFIGURATION
    # --------------------------------------------
    apply_to_specific_task = fields.Boolean(string='Aplicar solo en este grupo')
    dynamic_field_name = fields.Char(string='Nombre', invisible="1")
    dynamic_field_label = fields.Char(string='Nombre del Campo' )
    dynamic_field_type = fields.Selection([
        ('char', 'Text'),
        ('text', 'Long Text'),
        ('html', 'HTML'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('boolean', 'Boolean'),
        ('date', 'Date'),
        ('datetime', 'Datetime')
    ], string='Field Type', default='char')
    dynamic_fields_data = fields.Text(string='Dynamic Fields Data')
    dynamic_field_list = fields.Text(string='Dynamic Fields List', compute='_compute_dynamic_fields')

   
    # --------------------------------------------
    # COMPUTE METHODS
    # --------------------------------------------
    @api.depends('department_id')
    def _compute_allowed_members(self):
        for task in self:
            if task.department_id and task.department_id.pick_from_dept:
                # Usar los miembros del tablero (boards.planner)
                task.allowed_member_ids = task.department_id.member_ids
            else:
                # Permitir cualquier empleado si no hay restricción
                task.allowed_member_ids = self.env['hr.employee'].search([])

    @api.depends('subtask_ids.state')
    def _compute_progress(self):
        for task in self:
            subtasks = task.subtask_ids
            total = len(subtasks)
            done = len(subtasks.filtered(lambda x: x.state == 'done'))
            task.total_subtasks = total
            task.completed_subtasks = done
            progress = total and (done * 100.0 / total) or 0
            task.progress = progress
            
            if progress >= 100 and task.state != 'done':
                task.state = 'done'
            elif progress > 0 and progress < 100 and task.state != 'in_progress':
                task.state = 'in_progress'

    @api.depends('state')
    def _compute_color_from_state(self):
        color_mapping = {
            'new': 2,      # Amarillo
            'in_progress': 5,  # Naranja
            'done': 10,     # Verde
            'stuck': 1,     # Rojo
            'view_subtasks': 4  # Azul claro
        }
        for task in self:
            task.color = color_mapping.get(task.state, 0)

    def _compute_has_dynamic_fields(self):
        """Compute si hay campos dinámicos para mostrar la sección"""
        dynamic_fields = self.env['ir.model.fields'].search([
            ('model', '=', 'task.board'),
            ('name', 'like', 'x_%'),
            ('store', '=', True)
        ])
        for record in self:
            record.has_dynamic_fields = bool(dynamic_fields)

    @api.depends('dynamic_fields_data')
    def _compute_dynamic_fields(self):
        for task in self:
            try:
                dynamic_data = json.loads(task.dynamic_fields_data or '{}')
                field_info = {
                    'fields': [],
                    'field_attrs': {}
                }
                
                for field_name, field_config in dynamic_data.items():
                    if isinstance(field_config, dict):
                        field_info['fields'].append(field_name)
                        field_info['field_attrs'][field_name] = {
                            'string': field_config.get('label', field_name.replace('_', ' ').title()),
                            'widget': field_config.get('widget', False),
                            'options': field_config.get('options', {})
                        }
                
                task.dynamic_field_list = field_info
            except Exception as e:
                _logger.error("Error computing dynamic fields: %s", str(e))
                task.dynamic_field_list = {
                    'fields': [],
                    'field_attrs': {}
                }

    # --------------------------------------------
    # CONSTRAINTS AND VALIDATION
    # --------------------------------------------
    @api.model
    def create(self, vals):
        # Validación de campos obligatorios
        required_fields = ['name', 'person', 'department_id']
        for field in required_fields:
            if not vals.get(field):
                raise ValidationError(_("El campo %s es obligatorio") % field)
        
        # Validación de empleado en miembros permitidos
        person_id = vals.get('person')
        department_id = vals.get('department_id')
        
        if person_id and department_id:
            employee = self.env['hr.employee'].browse(person_id)
            department = self.env['boards.planner'].browse(department_id)
            
            if not employee.exists():
                raise ValidationError(_("El empleado seleccionado no existe"))
            
            if not department.exists():
                raise ValidationError(_("El tablero seleccionado no existe"))
            
            # Verificar si el empleado está en los miembros permitidos del tablero
            if department.pick_from_dept and employee not in department.member_ids:
                raise ValidationError(_(
                    "El empleado %s no está en la lista de miembros permitidos del tablero %s. "
                    "Verifica la asignación."
                ) % (employee.name, department.name))
        
        return super().create(vals)

    def write(self, vals):
        for record in self:
            # Verificar si se está modificando el nombre y si está vacío
            if 'name' in vals and not vals['name']:
                raise ValidationError(_("El nombre de la tarea no puede estar vacío"))
            
            # Obtener valores actuales o nuevos
            current_person = vals.get('person', record.person.id)
            current_department = vals.get('department_id', record.department_id.id)
            
            # Validar relación empleado-tablero
            if current_person and current_department:
                employee = self.env['hr.employee'].browse(current_person)
                department = self.env['boards.planner'].browse(current_department)
                
                if not employee.exists():
                    raise ValidationError(_("El empleado seleccionado no existe"))
                
                if not department.exists():
                    raise ValidationError(_("El tablero seleccionado no existe"))
                
                # Verificar si el empleado está en los miembros permitidos del tablero
                if department.pick_from_dept and employee not in department.member_ids:
                    raise ValidationError(_(
                        "El empleado %s no está en la lista de miembros permitidos del tablero %s. "
                        "Verifica la asignación."
                    ) % (employee.name, department.name))
        
        return super().write(vals)

    @api.constrains('name', 'person', 'department_id')
    def _check_required_fields(self):
        """Validación adicional para integridad de datos"""
        for record in self:
            if not record.name:
                raise ValidationError(_("El nombre de la tarea es obligatorio"))
            if not record.person:
                raise ValidationError(_("Debe asignar un responsable"))
            if not record.department_id:
                raise ValidationError(_("Debe seleccionar un tablero"))
            
            # Validar que el empleado esté en los miembros permitidos del tablero
            if (record.department_id.pick_from_dept and 
                record.person not in record.department_id.member_ids):
                raise ValidationError(_(
                    "El empleado %s no está en la lista de miembros permitidos del tablero %s. "
                    "Verifica la asignación."
                ) % (record.person.name, record.department_id.name))

    # ... (el resto de los métodos se mantienen igual, solo asegúrate de que
    # las referencias a 'department_id' sean consistentes)

    def action_toggle_subtasks(self):
        """Alternar visibilidad de subtareas sin cambiar el estado principal"""
        self.ensure_one()
        return self.write({
            'show_subtasks': not self.show_subtasks,
            'state': 'view_subtasks' if not self.show_subtasks else self._get_previous_state()
        })
        
    def _get_previous_state(self):
        """Obtener el estado apropiado basado en el progreso"""
        if self.progress >= 100:
            return 'done'
        elif self.progress > 0:
            return 'in_progress'
        return 'new'

    def action_save(self):
        return True
          
    def _compute_has_dynamic_fields(self):
        """Compute si hay campos dinámicos para mostrar la sección"""
        dynamic_fields = self.env['ir.model.fields'].search([
            ('model', '=', 'task.board'),
            ('name', 'like', 'x_%'),
            ('store', '=', True)
        ])
        for record in self:
            record.has_dynamic_fields = bool(dynamic_fields)

    @api.depends('subtask_ids.state')
    def _compute_progress(self):
        for task in self:
            subtasks = task.subtask_ids
            total = len(subtasks)
            done = len(subtasks.filtered(lambda x: x.state == 'done'))
            task.total_subtasks = total
            task.completed_subtasks = done
            progress = total and (done * 100.0 / total) or 0
            task.progress = progress
            
            if progress >= 100 and task.state != 'done':
                task.state = 'done'
            elif progress > 0 and progress < 100 and task.state != 'in_progress':
                task.state = 'in_progress'
    
    @api.depends('state')
    def _compute_color_from_state(self):
        color_mapping = {
            'new': 2,      # Amarillo
            'in_progress': 5,  # Naranja
            'done': 10,     # Verde
            'stuck': 1,     # Rojo
            'view_subtasks': 4  # Azul claro
        }
        for task in self:
            task.color = color_mapping.get(task.state, 0)  # 0 es el valor por defecto
    
    @api.depends('department_id')
    def _compute_allowed_members(self):
        for task in self:
            if task.department_id and task.department_id.pick_from_dept:
                task.allowed_member_ids = task.department_id.member_ids
            else:
                task.allowed_member_ids = self.env['hr.employee'].search([])

    @api.depends('dynamic_fields_data')
    def _compute_dynamic_fields(self):
        for task in self:
            try:
                dynamic_data = json.loads(task.dynamic_fields_data or '{}')
                field_info = {
                    'fields': [],
                    'field_attrs': {}
                }
                
                for field_name, field_config in dynamic_data.items():
                    if isinstance(field_config, dict):
                        field_info['fields'].append(field_name)
                        field_info['field_attrs'][field_name] = {
                            'string': field_config.get('label', field_name.replace('_', ' ').title()),
                            'widget': field_config.get('widget', False),
                            'options': field_config.get('options', {})
                        }
                
                task.dynamic_field_list = field_info
            except Exception as e:
                _logger.error("Error computing dynamic fields: %s", str(e))
                task.dynamic_field_list = {
                    'fields': [],
                    'field_attrs': {}
                }
    # --------------------------------------------
    # DATABASE SCHEMA METHODS
    # --------------------------------------------
    def _repair_database_schema(self):
        """Repara automáticamente el esquema de la base de datos"""
        try:
            # Verificar y crear columnas faltantes
            self._create_column_if_missing('ir_model', 'varchar')
            self._create_column_if_missing('ir_model_fields', 'varchar')
            # Actualizar valores si es necesario
            self._update_missing_keys()
            return True
        except Exception as e:
            _logger.error("Error repairing schema: %s", str(e))
            return False

    def _create_column_if_missing(self, table_name, column_name, column_type):
        """Crea una columna si no existe"""
        self.env.cr.execute(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table_name}' 
            AND column_name = '{column_name}'
        """)
        if not self.env.cr.fetchone():
            try:
                self.env.cr.execute(f"""
                    ALTER TABLE "{table_name}" 
                    ADD COLUMN "{column_name}" {column_type}
                """)
                self.env.cr.commit()
                _logger.info(f"Created column {column_name} in {table_name}")
            except Exception as e:
                _logger.error(f"Failed to create column {column_name}: {str(e)}")
                self.env.cr.rollback()
    # --------------------------------------------
    # DYNAMIC FIELD METHODS
    # --------------------------------------------
    def action_create_dynamic_field(self):
        """Método principal con manejo de errores mejorado"""
        self.ensure_one()

        if not self.dynamic_field_name or not self.dynamic_field_type:
            raise UserError("Nombre y tipo de campo son requeridos")

        field_name = self._generate_valid_field_name(self.dynamic_field_name)

        try:
            # 1. Crear el campo en el modelo
            self._create_field_in_model(field_name)

            # 2. Actualizar vistas
            task_id = self.id if self.apply_to_specific_task else None
            self._update_kanban_view(field_name, task_id)
            self._update_form_view(field_name, task_id)

            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
                'params': {'wait': True}  # Esperar recarga completa
            }

        except Exception as e:
            self._remove_field_artifacts(field_name)
            raise UserError(f"Error creando campo: {str(e)}")

    def _verify_field_in_kanban(self, field_name):
        """Verifica que el campo está en la vista kanban"""
        try:
            # Buscar la vista heredada
            view = self.env['ir.ui.view'].search([
                ('name', 'like', f'{self._name}.kanban.dynamic.{field_name}'),
                ('model', '=', self._name)
            ], limit=1)
            if not view:
                _logger.error("No se encontró la vista heredada")
                return False

            # Verificar que el campo está en el XML
            if field_name not in (view.arch_db or ''):
                _logger.error("El campo no está en el archivo XML de la vista")
                return False

            return True
        except Exception as e:
            _logger.error(f"Error en verificación: {str(e)}")
            return False

    def _create_field_in_model(self, field_name):
        """Robust field creation with existence checking"""
        try:
            # Check if field already exists
            existing_field = self.env['ir.model.fields'].sudo().search([
                ('model', '=', self._name),
                ('name', '=', field_name)
            ], limit=1)

            if existing_field:
                # Field exists - update it instead of creating new
                field_vals = self._prepare_field_vals(field_name)
                existing_field.write(field_vals)
                _logger.info("Updated existing field %s", field_name)
                return existing_field

            # Field doesn't exist - create new
            field_vals = self._prepare_field_vals(field_name)
            field = self.env['ir.model.fields'].sudo().create(field_vals)

            # Add column to database
            self._add_column_to_table(field_name, self.dynamic_field_type)

            # Create translation if needed
            self._create_safe_translation(field.id, field_vals.get('field_description', field_name))
            return field
        except Exception as e:
            _logger.error("Field creation/update failed for %s: %s", field_name, str(e))
            raise UserError(_("Error creating/updating field: %s") % str(e))

    def _prepare_field_vals(self, field_name):
        """Prepare field values dictionary"""
        field_description = self.dynamic_field_label or field_name.replace('_', ' ').title()
        field_vals = {
            'name': field_name,
            'model_id': self.env['ir.model'].sudo().search([('model', '=', self._name)]).id,
            'field_description': field_description,
            'ttype': self.dynamic_field_type,
            'state': 'manual',
            'store': True,
            'required': False,
        }

        if self.dynamic_field_type == 'selection' and self.selection_options:
            selection = []
            for line in self.selection_options.split('\n'):
                if line.strip() and ':' in line:
                    key, val = map(str.strip, line.split(':', 1))
                    selection.append((key, val))
            if selection:
                field_vals['selection'] = str(selection)
        return field_vals

    def _generate_valid_field_name(self, name):
        """Genera un nombre de campo válido"""
        name = re.sub(r'[^a-zA-Z0-9_]', '', name.lower().replace(' ', '_'))
        if not name.startswith('x_'):
            name = f'x_{name}'
        if len(name) > 2 and name[2].isdigit():
            name = f'x_field_{name[2:]}'
        return name

    def _create_field_in_model(self, field_name):
        """Versión robusta para crear campos sin dependencia de 'key'"""
        try:
            # 1. Obtener o crear el registro del modelo
            model = self.env['ir.model'].sudo().search([('model', '=', self._name)])
            if not model:
                model = self.env['ir.model'].sudo().create({
                    'name': 'Task Board',
                    'model': self._name,
                })

            # 2. Preparar valores del campo
            field_description = self.dynamic_field_label or field_name.replace('_', ' ').title()
            field_vals = {
                'name': field_name,
                'model_id': model.id,
                'field_description': field_description,
                'ttype': self.dynamic_field_type,
                'state': 'manual',
                'store': True,
                'required': False,
            }

            # 3. Manejar campos de selección
            if self.dynamic_field_type == 'selection' and self.selection_options:
                selection = []
                for line in self.selection_options.split('\n'):
                    if line.strip() and ':' in line:
                        key, val = map(str.strip, line.split(':', 1))
                        selection.append((key, val))
                if selection:
                    field_vals['selection'] = str(selection)

            # 4. Crear el campo con manejo de errores
            try:
                field = self.env['ir.model.fields'].sudo().create(field_vals)
                self._add_column_to_table(field_name, self.dynamic_field_type)
                self._create_safe_translation(field.id, field_description)
                return field
            except Exception as e:
                _logger.error("Failed to create field: %s", str(e))
                raise

        except Exception as e:
            _logger.error("Field creation process failed: %s", str(e))
            raise UserError(_("Error creating field: %s") % str(e))

    def _create_safe_translation(self, field_id, description):
        """Método seguro para crear traducciones"""
        try:
            # Verificar si el módulo de traducción está instalado
            if not self.env['ir.module.module'].search(
                [('name', '=', 'base'), ('state', '=', 'installed')]
            ):
                return False

            # Crear traducción solo si no existe
            existing = self.env['ir.translation'].search([
                ('name', '=', 'ir.model.fields,field_description'),
                ('res_id', '=', field_id),
                ('lang', '=', self.env.user.lang)
            ])
            
            if not existing:
                self.env['ir.translation'].sudo().create({
                    'name': 'ir.model.fields,field_description',
                    'type': 'model',
                    'lang': self.env.user.lang,
                    'res_id': field_id,
                    'value': description,
                    'state': 'translated'
                })
            return True
        except Exception as e:
            _logger.warning("Could not create translation: %s", str(e))
            return False

    def _add_column_to_table(self, field_name, field_type):
        """Añadir columna con manejo robusto de errores"""
        type_mapping = {
            'char': 'VARCHAR(255)',
            'text': 'TEXT',
            'html': 'TEXT',
            'integer': 'INTEGER',
            'float': 'NUMERIC',
            'boolean': 'BOOLEAN',
            'selection': 'VARCHAR(255)',
            'date': 'DATE',
            'datetime': 'TIMESTAMP'
        }
        
        column_type = type_mapping.get(field_type, 'VARCHAR(255)')
        
        try:
            self.env.cr.execute(f"""
                ALTER TABLE "{self._table}" 
                ADD COLUMN IF NOT EXISTS "{field_name}" {column_type}
            """)
            return True
        except Exception as e:
            _logger.error("Failed to add column %s: %s", field_name, str(e))
            raise UserError(_("Failed to create database column. Error: %s") % str(e))

    def _create_initial_translation(self, field_id, description):
        """Create initial translations for the field"""
        langs = self.env['res.lang'].search([])
        for lang in langs:
            self.env['ir.translation'].sudo().create({
                'name': 'ir.model.fields,field_description',
                'type': 'model',
                'lang': lang.code,
                'res_id': field_id,
                'value': description,
                'state': 'translated'
            })

    def _store_field_metadata(self, field_name):
        """Store field configuration in JSON"""
        self.ensure_one()
        try:
            current_data = json.loads(self.dynamic_fields_data or '{}')
            field_config = {
                'type': self.dynamic_field_type,
                'label': self.dynamic_field_label or field_name.replace('_', ' ').title(),
                'task_specific': bool(self.apply_to_specific_task),
                'created_at': fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'created_by': self.env.user.id
            }

            if self.dynamic_field_type == 'selection' and self.selection_options:
                options = []
                for line in self.selection_options.split('\n'):
                    if line.strip() and ':' in line:
                        key, val = map(str.strip, line.split(':', 1))
                        options.append((key, val))
                field_config['options'] = options

            current_data[field_name] = field_config
            self.dynamic_fields_data = json.dumps(current_data)
        except Exception as e:
            _logger.error("Error storing field metadata: %s", str(e))
            raise

    # --------------------------------------------
    # VIEW METHODS
    # --------------------------------------------
    def _update_views_for_specific_task(self, field_name, task_id):
        """Update views to show field only for specific task"""
        self._update_form_view(field_name, task_specific=True, task_id=task_id)
        self._update_kanban_view(field_name, task_specific=True, task_id=task_id)
    
    def _update_views_globally(self, field_name):
        """Update views to show field for all tasks"""
        self._update_form_view(field_name)
        self._update_kanban_view(field_name)
    
    def _update_form_view(self, field_name, task_specific=False, task_id=None):
        """Update form view to include the new field"""
        view_ref = 'task_planner.activity_planner_details_view_form'
        base_view = self.env.ref(view_ref)
        
        field_attrs = {
            'name': field_name,
            'string': self.dynamic_field_label or field_name.replace('_', ' ').title(),
        }
        
        if self.dynamic_field_type == 'html':
            field_attrs['widget'] = 'html'
        elif self.dynamic_field_type == 'selection':
            field_attrs['widget'] = 'selection'
        elif self.dynamic_field_type in ['date', 'datetime']:
            field_attrs['widget'] = self.dynamic_field_type
        
        if task_specific:
            arch = f"""
            <data>
                <xpath expr="//sheet" position="inside">
                    <div t-if="id == {task_id}">
                        <field {' '.join(f'{k}="{v}"' for k, v in field_attrs.items())}/>
                    </div>
                </xpath>
            </data>
            """
        else:
            arch = f"""
            <data>
                <xpath expr="//sheet" position="inside">
                    <field {' '.join(f'{k}="{v}"' for k, v in field_attrs.items())}/>
                </xpath>
            </data>
            """
        view_name = f"{self._name}.form.{f'task_{task_id}.' if task_specific else ''}{field_name}"
        self._create_or_update_view(view_name, self._name, base_view.id, arch, 'form')
    
    def _update_kanban_view(self, field_name, specific_task_id=None):
        """
        Inserta dinámicamente un campo como COLUMNA en la vista kanban,
        solo para el ID específico cuando se proporciona
        """
        try:
            # 1. Obtener vista kanban base
            kanban_view = self.env.ref('task_planner.activity_planner_task_view_kanban')
            if not kanban_view:
                raise UserError("Vista kanban base no encontrada")
    
            # 2. Configurar atributos del campo
            field_label = self.dynamic_field_label or field_name.replace('_', ' ').title()
            field_attrs = {
                'name': field_name,
                'string': field_label,
            }
    
            # 3. Añadir widget si aplica
            if self.dynamic_field_type == 'html':
                field_attrs['widget'] = 'html'
            elif self.dynamic_field_type in ['selection', 'date', 'datetime']:
                field_attrs['widget'] = self.dynamic_field_type
            elif self.dynamic_field_type == 'boolean':
                field_attrs['widget'] = 'boolean_toggle'
    
            # 4. Construir XML dinámico como COLUMNA
            task_id = int(specific_task_id) if specific_task_id else None
            t_if_condition = f't-if="record.id.raw_value == {task_id}"' if task_id else ''
            
            field_line = " ".join(f'{k}="{v}"' for k, v in field_attrs.items())
    
            arch = f"""
            <data>
                <!-- Añadir encabezado de columna -->
                <xpath expr="//table[@class='kanban_table']/thead/tr/th[.='Fecha']" position="after">
                    <th {t_if_condition}>{field_label}</th>
                </xpath>
                
                <!-- Añadir celda en los registros -->
                <xpath expr="//table[@class='kanban_table']/tbody/tr/td[./field[@name='completion_date']]" position="after">
                    <td {t_if_condition}>
                        <field {field_line}/>
                    </td>
                </xpath>
            </data>
            """
    
            # 5. Crear o reemplazar vista heredada
            view_name = f"{self._name}.kanban.dynamic.{field_name}.{task_id or 'global'}"
    
            # Eliminar versiones anteriores
            self.env['ir.ui.view'].search([
                ('name', '=like', f"{self._name}.kanban.dynamic.{field_name}%"),
                ('model', '=', self._name)
            ]).unlink()
    
            # Crear nueva vista
            self.env['ir.ui.view'].create({
                'name': view_name,
                'type': 'kanban',
                'model': self._name,
                'inherit_id': kanban_view.id,
                'arch_base': arch,
                'priority': 99,
            })
    
            # 6. Limpieza de caché forzada
            self.env.invalidate_all()
            self.env['ir.ui.view'].clear_caches()
            return True
    
        except Exception as e:
            error_msg = f"Error actualizando kanban: {str(e)}"
            _logger.error(error_msg)
            raise UserError(error_msg)

    def _force_cache_reload(self):
        """Limpieza de caché completa"""
        try:
            self.env.invalidate_all()
            if hasattr(self.env.registry, '_clear_cache'):
                self.env.registry._clear_cache()
            self.env['ir.ui.view'].clear_caches()
            if 'ir.asset' in self.env:
                self.env['ir.asset']._generate_assets()
            return True
        except Exception as e:
            _logger.error(f"Error en limpieza de caché: {str(e)}")
            return False

    def _safe_cache_cleanup(self):
        """Limpieza de caché que no interfiere con la creación de registros"""
        try:
            # 1. Invalidar cachés básicos
            self.env.invalidate_all()

            # 2. Limpiar caché de vistas
            self.env['ir.ui.view'].clear_caches()

            # 3. Limpieza adicional solo si es necesario
            if hasattr(self.env.registry, '_clear_cache'):
                self.env.registry._clear_cache()

            return True
        except Exception as e:
            _logger.warning(f"Error no crítico en limpieza de caché: {str(e)}")
            return True
    
    def _create_or_update_view(self, view_name, model, inherit_id, arch, view_type):
        """Helper to create or update a view"""
        try:
            # Buscar si ya existe una vista heredada para este campo
            existing_view = self.env['ir.ui.view'].search([
                ('name', '=', view_name),
                ('model', '=', model)
            ], limit=1)

            if existing_view:
                # Actualizar vista existente
                existing_view.write({'arch_base': arch})
            else:
                # Crear nueva vista heredada
                self.env['ir.ui.view'].create({
                    'name': view_name,
                    'type': view_type,
                    'model': model,
                    'inherit_id': inherit_id,
                    'arch': arch,
                    'priority': 100,  # Alta prioridad para asegurar que se aplique
                })

            # Limpiar cachés críticos
            self.env['ir.ui.view'].clear_caches()
            if hasattr(self.env.registry, '_clear_cache'):
                self.env.registry._clear_cache()

            return True
        except Exception as e:
            _logger.error("Error creating/updating view %s: %s", view_name, str(e))
            raise UserError(_("Error updating view: %s") % str(e))

    # --------------------------------------------
    # FIELD REMOVAL METHODS
    # --------------------------------------------
    def _get_existing_dynamic_fields(self):
        """Obtiene todos los campos dinámicos extra agregados por el usuario"""
        # Lista de campos estáticos originales del modelo
        ORIGINAL_FIELDS = {
            'name', 'sequence', 'completion_date', 'department_id', 'person', 
            'allowed_member_ids', 'state', 'color', 'files', 'show_subtasks',
            'subtask_ids', 'subtasks_count', 'completed_subtasks', 'total_subtasks',
            'progress', 'apply_to_specific_task', 'dynamic_field_name', 
            'dynamic_field_label', 'dynamic_field_type', 'selection_options',
            'dynamic_fields_data', 'dynamic_field_list', 'has_dynamic_fields'
        }

        # Buscar todos los campos manuales del modelo
        dynamic_fields = self.env['ir.model.fields'].sudo().search([
            ('model', '=', 'task.board'),
            ('state', '=', 'manual')
        ])

        # Filtrar solo los campos que no son originales y existen en DB
        extra_fields = []
        for field in dynamic_fields:
            if field.name not in ORIGINAL_FIELDS:
                try:
                    self.env.cr.execute("""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name = %s 
                        AND column_name = %s
                    """, [self._table, field.name])
                    if self.env.cr.fetchone():
                        extra_fields.append(field)
                except Exception:
                    continue

        return extra_fields

    def _get_dynamic_field_options(self):
        """Obtiene las opciones de campos dinámicos para el selection"""
        dynamic_fields = self._get_existing_dynamic_fields()
        return [(field.name, field.field_description) for field in dynamic_fields]

    def action_remove_dynamic_field(self):
       """Muestra diálogo con selección de campo a eliminar"""
       self.ensure_one()
       dynamic_fields = self._get_existing_dynamic_fields()

       if not dynamic_fields:
           raise UserError(_("No hay campos dinámicos adicionales para eliminar"))

       # Crear lista de opciones para mostrar
       field_options = [(field.name, field.field_description) for field in dynamic_fields]

       return {
           'name': _('Seleccionar campo a eliminar'),
           'type': 'ir.actions.act_window',
           'res_model': self._name,
           'view_mode': 'form',
           'view_id': self.env.ref('task_planner.view_remove_dynamic_field_selection').id,
           'target': 'new',
           'res_id': self.id,
           'context': {
               'field_options': field_options,
               'default_dynamic_field_to_remove': field_options[0][0] if field_options else False
           }
       }

    def remove_selected_field(self):
       """Elimina el campo seleccionado"""
       self.ensure_one()
       if not self.dynamic_field_to_remove:
           raise UserError(_("Por favor seleccione un campo para eliminar"))

       field_name = self.dynamic_field_to_remove
       
       try:
           # 1. Limpieza de caché inicial
           self._ultimate_cache_cleanup()
           # 2. Eliminar vistas asociadas
           self._remove_all_field_views(field_name)
           # 3. Eliminar definición del campo
           self._remove_field_definition(field_name)
           # 4. Eliminar metadatos
           self._remove_field_metadata(field_name)
           # 5. Eliminar columna de la base de datos
           self._safe_remove_column(field_name)
           # 6. Limpieza final de caché
           self._ultimate_cache_cleanup()

           return {
               'type': 'ir.actions.client',
               'tag': 'reload',
               'params': {'wait': True}
           }
       except Exception as e:
           _logger.error("Error removing field %s: %s", field_name, str(e))
           raise UserError(_("Error eliminando campo: %s") % str(e))

    def _remove_all_field_views(self, field_name):
        """Versión alternativa más agresiva"""
        try:
            # Eliminar todas las vistas que mencionen el campo en su nombre
            self.env['ir.ui.view'].search([
                ('model', '=', self._name),
                ('name', 'ilike', field_name)
            ]).unlink()
            
            # Buscar y eliminar cualquier vista personalizada relacionada
            # Esto puede variar según la versión de Odoo
            if 'ir.ui.view.custom' in self.env:
                self.env['ir.ui.view.custom'].search([
                    ('user_id', '=', self.env.uid)
                ]).unlink()
                
        except Exception as e:
            _logger.error("Alternative view removal failed: %s", str(e))
            # Si falla, al menos registrar el error pero continuar

    def _remove_field_artifacts(self, field_name):
        """Elimina todos los rastros del campo, incluyendo vistas específicas"""
        try:
            # 1. Eliminar todas las vistas asociadas al campo, no solo las kanban
            views = self.env['ir.ui.view'].search([
                ('name', 'like', f'{self._name}.%.{field_name}%'),
                ('model', '=', self._name)
            ])
            if views:
                views.unlink()
            # 2. Eliminar metadatos del campo
            self._remove_field_metadata(field_name)
            # 3. Eliminar definición del campo (intentar primero por ORM, luego por SQL)
            field = self.env['ir.model.fields'].sudo().search([
                ('model', '=', self._name),
                ('name', '=', field_name)
            ], limit=1)

            if field:
                try:
                    field.unlink()
                except Exception as e:
                    _logger.warning("Could not unlink field via ORM, trying SQL: %s", str(e))
                    self.env.cr.execute("""
                        DELETE FROM ir_model_fields
                        WHERE model = %s AND name = %s
                    """, [self._name, field_name])

            # 4. Eliminar columna de la base de datos
            self._safe_remove_column(field_name)

            # 5. Limpieza final de caché
            self._ultimate_cache_cleanup()

        except Exception as e:
            _logger.error("Error en limpieza completa de campo %s: %s", field_name, str(e))
            raise UserError(_("Error completo al eliminar campo: %s") % str(e))

    def _remove_field_metadata(self, field_name):
        """Remove field from stored JSON data for all records"""
        try:
            tasks_with_data = self.search([('dynamic_fields_data', '!=', False)])
            for task in tasks_with_data:
                if task.dynamic_fields_data:
                    try:
                        data = json.loads(task.dynamic_fields_data)
                        if field_name in data:
                            del data[field_name]
                            task.dynamic_fields_data = json.dumps(data)
                    except json.JSONDecodeError:
                        # Si hay datos corruptos, limpiar el campo completamente
                        task.dynamic_fields_data = False
        except Exception as e:
            _logger.error("Error removing field metadata: %s", str(e))
            raise
    
    def _remove_field_definition(self, field_name):
        """Elimina la definición del campo de manera más robusta"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Buscar el campo con sudo para evitar problemas de permisos
                field = self.env['ir.model.fields'].sudo().search([
                    ('model', '=', self._name),
                    ('name', '=', field_name)
                ], limit=1)

                if field:
                    # Primero intentar eliminar traducciones asociadas
                    self.env['ir.translation'].sudo().search([
                        ('name', '=', 'ir.model.fields,field_description'),
                        ('res_id', '=', field.id)
                    ]).unlink()

                    # Luego eliminar el campo
                    field.unlink()

                    # Verificar que realmente se eliminó
                    if self.env['ir.model.fields'].sudo().search([('id', '=', field.id)], count=True):
                        raise Exception("Field still exists after unlink")

                    return True

                return False

            except Exception as e:
                if attempt == max_attempts - 1:
                    _logger.error("Failed to remove field definition after %s attempts: %s", max_attempts, str(e))
                    # Último intento: eliminación directa por SQL
                    self.env.cr.execute("""
                        DELETE FROM ir_model_fields
                        WHERE model = %s AND name = %s
                    """, [self._name, field_name])
                    self.env.cr.commit()
                else:
                    time.sleep(0.5 * (attempt + 1))
    
    def _remove_field_from_views(self, field_name):
        """Remove all references to field in views"""
        views = self.env['ir.ui.view'].search([
            ('model', '=', self._name),
            ('arch_db', 'ilike', field_name)
        ])
        
        for view in views:
            try:
                if field_name in (view.arch_db or ''):
                    view.unlink()
            except Exception:
                pass
    
    def _safe_remove_column(self, field_name):
        """Safely remove column from database with proper transaction handling"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Start a new transaction
                self.env.cr.execute("BEGIN;")

                # Check if column exists
                self.env.cr.execute("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = %s 
                    AND column_name = %s
                """, [self._table, field_name])

                if self.env.cr.fetchone():
                    try:
                        self.env.cr.execute(
                            f'ALTER TABLE "{self._table}" DROP COLUMN IF EXISTS "{field_name}"'
                        )
                        self.env.cr.execute("COMMIT;")
                        _logger.info("Successfully removed column %s", field_name)
                        return True
                    except Exception as e:
                        self.env.cr.execute("ROLLBACK;")
                        _logger.warning("Attempt %d to drop column failed: %s", attempt + 1, str(e))
                        if attempt == max_attempts - 1:
                            raise
                        time.sleep(0.5 * (attempt + 1))
                else:
                    self.env.cr.execute("COMMIT;")
                    return False

            except Exception as e:
                _logger.error("Transaction failed completely: %s", str(e))
                try:
                    self.env.cr.execute("ROLLBACK;")
                except:
                    pass
                if attempt == max_attempts - 1:
                    raise UserError(_("Failed to remove column after %d attempts. Error: %s") % (max_attempts, str(e)))

    # --------------------------------------------
    # CACHE METHODS
    # --------------------------------------------
    def _ultimate_cache_cleanup(self):
        """Limpieza de caché más completa y efectiva"""
        try:
            # 1. Invalidar todas las cachés
            self.env.invalidate_all()

            # 2. Limpiar caché del registro
            if hasattr(self.env.registry, '_clear_cache'):
                self.env.registry._clear_cache()

            # 3. Limpiar caché de vistas específicamente
            if hasattr(self.env.registry, '_clear_view_cache'):
                self.env.registry._clear_view_cache()

            # 4. Limpiar caché de assets
            if 'ir.asset' in self.env:
                self.env['ir.asset']._generate_assets()

            # 5. Limpiar caché de campos calculados
            self.env.registry.setup_models(self.env.cr)

            # 6. Forzar recarga de la vista
            self.env['ir.ui.view'].clear_caches()

            # 7. Recargar el modelo en el registro
            if self._name in self.env.registry.models:
                self.env.registry.init_models(self.env.cr, [self._name], {'module': self._module or 'task_planner'})

        except Exception as e:
            _logger.error("Error in ultimate cache cleanup: %s", str(e))

    # --------------------------------------------
    # ACTION METHODS
    # --------------------------------------------
    def action_open_edit_form(self):
        self.ensure_one()

        # Obtener campos dinámicos existentes
        dynamic_fields = self.env['ir.model.fields'].search([
            ('model', '=', 'task.board'),
            ('name', 'like', 'x_%'),
            ('store', '=', True)
        ])

        # Buscar si ya existe una vista temporal para esta tarea
        existing_view = self.env['ir.ui.view'].search([
            ('name', '=', f'task.board.dynamic.fields.{self.id}'),
            ('model', '=', 'task.board')
        ], limit=1)

        # Generar XML para los campos dinámicos
        fields_xml = '\n'.join(
            f'<field name="{field.name}" string="{field.field_description}"/>'
            for field in dynamic_fields
        )

        arch = f"""
        <data>
            <xpath expr="//group" position="inside">
                <group string="Dynamic Fields" attrs="{{'invisible': [('has_dynamic_fields', '=', False)]}}">
                    {fields_xml}
                </group>
            </xpath>
        </data>
        """

        # Actualizar vista existente o crear nueva
        if existing_view:
            existing_view.write({'arch_base': arch})
            view_id = existing_view.id
        else:
            view_id = self.env['ir.ui.view'].create({
                'name': f'task.board.dynamic.fields.{self.id}',
                'model': 'task.board',
                'inherit_id': self.env.ref('task_planner.view_task_board_form').id,
                'arch_base': arch,
                'priority': 99,
            }).id

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'task.board',
            'view_mode': 'form',
            'res_id': self.id,
            'view_id': view_id,
            'target': 'new',
            'context': {'create': False}
        }

    def action_open_dynamic_field_creator(self):
        """Open dialog to create dynamic field"""
        self.ensure_one()
        return {
            'name': _('Add Dynamic Field'),
            'type': 'ir.actions.act_window',
            'res_model': 'task.board',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('task_planner.view_task_board_dynamic_fields_form').id,
            'target': 'new',
        }

    def action_custom_create_subtask(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Nueva Subtarea',
            'res_model': 'subtask.board',
            'view_mode': 'form',
            'view_id': self.env.ref('task_planner.view_subtask_form').id,  # Vista formulario específica
            'target': 'new',  # Abre en popup
            'context': {
                'default_task_id': self.task_id.id,
                'form_view_initial_mode': 'edit',
            },
        }
    
    def action_view_subtasks(self):
        self.ensure_one()
        return {
            'name': 'Tareas',
            'type': 'ir.actions.act_window',
            'res_model': 'subtask.board',
            'view_mode': 'tree,form',
            'views': [
                (self.env.ref('task_planner.view_subtask_tree').id, 'tree'),
                (self.env.ref('task_planner.activity_planner_subtask_form').id, 'form')
            ],
            'domain': [('task_id', '=', self.id)],
            'context': {
                'default_task_id': self.id,
                'search_default_task_id': self.id
            },
            'target': 'current',
        }

    def action_toggle_subtasks(self):
        """Toggle subtasks visibility"""
        for task in self:
            task.show_subtasks = not task.show_subtasks
        return True
    
    def open_details_form(self):
        """Open detailed form view"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Task Details'),
            'res_model': 'task.board',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('task_planner.activity_planner_details_view_form').id,
            'target': 'current',
            'flags': {'mode': 'readonly'} if self.state == 'done' else {}
        }
  
    # --------------------------------------------
    # CONSTRAINTS AND VALIDATION
    # --------------------------------------------
    
    @api.model
    def create(self, vals):
        # Validación de campos obligatorios
        required_fields = ['name', 'person', 'department_id']
        for field in required_fields:
            if not vals.get(field):
                raise ValidationError(_("El campo %s es obligatorio") % field)
        
        # Validación de departamento-empleado
        person_id = vals.get('person')
        department_id = vals.get('department_id')
        
        if person_id and department_id:
            employee = self.env['hr.employee'].browse(person_id)
            if not employee.exists():
                raise ValidationError(_("El empleado seleccionado no existe"))
            
            # Asegurarse de que el empleado tenga un departamento asignado
            if not employee.department_id:
                raise ValidationError(_("El empleado no tiene un departamento asignado"))
            
            # Convertir department_id a entero si es necesario
            selected_dept_id = department_id
            if isinstance(selected_dept_id, str):
                try:
                    selected_dept_id = int(selected_dept_id)
                except ValueError:
                    raise ValidationError(_("El ID del departamento no es válido"))
        
        return super().create(vals)

    def write(self, vals):
        # Validación al actualizar
        for record in self:
            # Verificar si se está modificando el nombre y si está vacío
            if 'name' in vals and not vals['name']:
                raise ValidationError(_("El nombre de la tarea no puede estar vacío"))
            
            # Obtener valores actuales o nuevos
            current_person = vals.get('person', record.person.id)
            current_department = vals.get('department_id', record.department_id.id)
            
            # Validar relación empleado-departamento
            if current_person and current_department:
                employee = self.env['hr.employee'].browse(current_person)
                if not employee.exists():
                    raise ValidationError(_("El empleado seleccionado no existe"))
              
        return super().write(vals)

    @api.constrains('name', 'person', 'department_id')
    def _check_required_fields(self):
        """Validación adicional para integridad de datos"""
        for record in self:
            if not record.name:
                raise ValidationError(_("El nombre de la tarea es obligatorio"))
            if not record.person:
                raise ValidationError(_("Debe asignar un responsable"))
            if not record.department_id:
                raise ValidationError(_("Debe seleccionar un departamento"))