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
    
    name = fields.Char(string='Task Name', required=True, tracking=True)
    sequence = fields.Integer(string='Sequence', default=10)
    completion_date = fields.Datetime(string='Due Date')
    department_id = fields.Many2one('boards.planner', string='Department', ondelete='cascade')
    person = fields.Many2one(
        'hr.employee',
        string='Assigned To',
        tracking=True,
        required=True,
        domain="[('id', 'in', allowed_member_ids)]"
    )
    allowed_member_ids = fields.Many2many(
        'hr.employee',
        compute='_compute_allowed_members',
        string='Allowed Members'
    )
    state = fields.Selection([
        ('new', 'New'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('stuck', 'Stuck'),
        ('view_subtasks', 'View Subtasks')
    ], string='Status', default='new', tracking=True)
    color = fields.Integer(string='Color Index', compute='_compute_color_from_state', store=True)
    files = fields.Many2many('ir.attachment', string='Attachments')
    show_subtasks = fields.Boolean(string='Show Subtasks')
    
    # --------------------------------------------
    # SUBTASK RELATED FIELDS
    # --------------------------------------------
    subtask_ids = fields.One2many('subtask.board', 'task_id', string='Subtasks')
    subtasks_count = fields.Integer(string='Subtask Count', compute='_compute_progress', store=True)
    completed_subtasks = fields.Integer(string='Completed Subtasks', compute='_compute_progress', store=True)
    total_subtasks = fields.Integer(string='Total Subtasks', compute='_compute_progress', store=True)
    progress = fields.Float(string='Progress', compute='_compute_progress', store=True, group_operator="avg")
    
    # --------------------------------------------
    # DYNAMIC FIELDS CONFIGURATION
    # --------------------------------------------
    apply_to_specific_task = fields.Boolean(string='Apply to Specific Task')
    dynamic_field_name = fields.Char(string='Technical Name')
    dynamic_field_label = fields.Char(string='Display Label')
    dynamic_field_type = fields.Selection([
        ('char', 'Text'),
        ('text', 'Long Text'),
        ('html', 'HTML'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('boolean', 'Boolean'),
        ('selection', 'Selection'),
        ('date', 'Date'),
        ('datetime', 'Datetime')
    ], string='Field Type', default='char')
    selection_options = fields.Text(string='Selection Options')
    dynamic_fields_data = fields.Text(string='Dynamic Fields Data')
    dynamic_field_list = fields.Text(string='Dynamic Fields List', compute='_compute_dynamic_fields')

    # --------------------------------------------
    # COMPUTE METHODS
    # --------------------------------------------
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
        for task in self:
            if task.state == 'new':
                task.color = 2  # Yellow
            elif task.state == 'in_progress':
                task.color = 5  # Orange
            elif task.state == 'done':
                task.color = 10  # Green
            elif task.state == 'stuck':
                task.color = 1  # Red
            elif task.state == 'view_subtasks':
                task.color = 4  # Light blue
            else:
                task.color = 0  # Default
    
    @api.depends('department_id')
    def _compute_allowed_members(self):
        for task in self:
            task.allowed_member_ids = task.department_id.member_ids

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
                            'type': field_config.get('type', 'char'),
                            'string': field_config.get('label', field_name),
                            'widget': field_config.get('widget', False),
                            'options': field_config.get('options', False)
                        }
                
                task.dynamic_field_list = json.dumps(field_info)
            except Exception as e:
                _logger.error("Error computing dynamic fields: %s", str(e))
                task.dynamic_field_list = json.dumps({
                    'fields': [],
                    'field_attrs': {}
                })

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
                <xpath expr="//table[@class='kanban_table']/thead/tr/th[.='Due Date']" position="after">
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
    def action_remove_dynamic_field(self):
        """Remove a dynamic field completely"""
        self.ensure_one()
        
        if not self.dynamic_field_name:
            raise UserError(_("Please specify the field name to remove"))
        
        field_name = self._generate_valid_field_name(self.dynamic_field_name)
        
        try:
            self._remove_field_artifacts(field_name)
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        except Exception as e:
            _logger.error("Error removing field %s: %s", field_name, str(e))
            raise UserError(_("Error removing field: %s") % str(e))
    
    def _remove_field_artifacts(self, field_name):
        """Elimina todos los rastros del campo, incluyendo vistas específicas"""
        try:
            # Eliminar vistas específicas primero
            views = self.env['ir.ui.view'].search([
                ('name', 'like', f'{self._name}.kanban.dynamic.{field_name}%'),
                ('model', '=', self._name)
            ])
            views.unlink()

            # Resto de la limpieza (metadata, definición de campo, etc.)
            self._remove_field_metadata(field_name)
            self._remove_field_definition(field_name)
            self._safe_remove_column(field_name)

            # Limpieza final de caché
            self._ultimate_cache_cleanup()
        except Exception as e:
            _logger.error("Error en limpieza: %s", str(e))
            raise

    def _remove_field_metadata(self, field_name):
        """Remove field from stored JSON data"""
        self.ensure_one()
        
        if not self.dynamic_fields_data:
            return
            
        try:
            data = json.loads(self.dynamic_fields_data)
            if field_name in data:
                del data[field_name]
                self.dynamic_fields_data = json.dumps(data)
        except Exception:
            pass
    
    def _remove_field_definition(self, field_name):
        """Remove the field from ir.model.fields"""
        field = self.env['ir.model.fields'].search([
            ('model', '=', self._name),
            ('name', '=', field_name)
        ], limit=1)
        
        if field:
            try:
                field.unlink()
            except Exception:
                self.env.cr.execute("""
                    DELETE FROM ir_model_fields
                    WHERE model = %s AND name = %s
                """, [self._name, field_name])
    
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
        """Limpieza de caché más efectiva"""
        try:
            # 1. Invalidar cachés de modelos
            self.env.invalidate_all()

            # 2. Limpiar caché del registro
            if hasattr(self.env.registry, '_clear_cache'):
                self.env.registry._clear_cache()

            # 3. Limpiar caché de vistas
            self.env['ir.ui.view'].clear_caches()

            # 4. Limpiar caché de traducciones
            if 'ir.translation' in self.env:
                self.env['ir.translation'].clear_caches()

            # 5. Regenerar assets
            if 'ir.asset' in self.env:
                self.env['ir.asset']._generate_assets()

            # 6. Forzar recarga de campos
            self.env.registry.setup_models(self.env.cr)

            return True
        except Exception as e:
            _logger.error("Error en limpieza de caché: %s", str(e))
            return False

    # --------------------------------------------
    # ACTION METHODS
    # --------------------------------------------
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
    
    def action_view_subtasks(self):
        """View subtasks action"""
        self.ensure_one()
        return {
            'name': _('Subtasks'),
            'type': 'ir.actions.act_window',
            'res_model': 'subtask.board',
            'view_mode': 'tree,form',
            'domain': [('task_id', '=', self.id)],
            'context': {
                'default_task_id': self.id,
                'search_default_task_id': self.id,
                'form_view_initial_mode': 'edit',
                'create': True
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
    @api.constrains('person', 'department_id')
    def _check_person_in_department(self):
        for task in self:
            if task.department_id and task.person not in task.department_id.member_ids:
                raise ValidationError(_(
                    "The assigned employee doesn't belong to the selected department. "
                    "Valid members: %s") % ", ".join(task.department_id.member_ids.mapped('name')))

    # --------------------------------------------
    # CRUD OVERRIDES
    # --------------------------------------------
    @api.model
    def create(self, vals):
        """Override create to check department assignment"""
        task = super().create(vals)
        task._check_person_in_department()
        return task
    
    def write(self, vals):
        """Override write to check department assignment"""
        res = super().write(vals)
        self._check_person_in_department()
        return res