from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from lxml import etree
import json
import re
import logging
import time
import datetime

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
        store=False
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
    
    dynamic_fields_data = fields.Text(
        string='Datos de Campos Dinámicos',
        help='Almacena la configuración de campos dinámicos en formato JSON'
    )
    # --------------------------------------------
    # SUBTASK RELATED FIELDS
    # --------------------------------------------
    subtask_ids = fields.One2many('subtask.board', 'task_id', string='Tareas', store=True)
    subtasks_count = fields.Integer(string='Numero de Tareas', compute='_compute_progress', store=True)
    completed_subtasks = fields.Integer(string='Tareas Completadas', compute='_compute_progress', store=True)
    total_subtasks = fields.Integer(string='Total de Tareas', compute='_compute_progress', store=True)
    progress = fields.Float(string='Progreso', compute='_compute_progress', store=True)
    
    # --------------------------------------------
    # DYNAMIC FIELDS CONFIGURATION
    # --------------------------------------------
    apply_to_specific_task = fields.Boolean(string='Aplicar solo en este grupo')
    dynamic_field_name = fields.Char(string='Nombre', invisible="1")
    dynamic_field_label = fields.Char(string='Nombre del Campo')
    dynamic_field_type = fields.Selection([
        ('char', 'Text'),
        ('text', 'Long Text'),
        ('html', 'HTML'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('boolean', 'Boolean'),
        ('date', 'Date'),
        ('datetime', 'Datetime'),
        ('selection', 'Selection'),
    ], string='Field Type', default='char')
    selection_options = fields.Text(string='Opciones de Selección')
    dynamic_field_list = fields.Text(string='Dynamic Fields List', compute='_compute_dynamic_fields')
    field_info = fields.Text(string='Ingresar datos para el campo')
    sequence_number = fields.Integer(string='Sequence Number')
    task_id = fields.Many2one('task.board', string='Task Board')
    activity_line_ids = fields.One2many('mail.activity', 'res_id', string='Activities')
    # --------------------------------------------
    # COMPUTE METHODS
    # --------------------------------------------
    @api.depends('department_id')
    def _compute_allowed_members(self):
        for task in self:
            if task.department_id and task.department_id.pick_from_dept:
                task.allowed_member_ids = task.department_id.member_ids.ids
            else:
                task.allowed_member_ids = self.env['hr.employee'].search([]).ids

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
        for record in self:
            dynamic_fields = self.env['ir.model.fields'].search([
                ('model', '=', 'task.board'),
                ('name', 'like', 'x_%'),
                ('store', '=', True)
            ])
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
                
                # Guardamos como JSON (texto) para evitar problemas de tipo en vistas
                task.dynamic_field_list = json.dumps(field_info, default=str)
            except Exception as e:
                _logger.error("Error computing dynamic fields: %s", str(e))
                task.dynamic_field_list = json.dumps({'fields': []})

    # --------------------------------------------
    # DATABASE SCHEMA METHODS
    # --------------------------------------------
    def _repair_database_schema(self):
        """Repara automáticamente el esquema de la base de datos"""
        try:
            self._create_column_if_missing('ir_model', 'varchar')
            self._create_column_if_missing('ir_model_fields', 'varchar')
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

    # ===========================
    # DYNAMIC FIELD CREATION METHODS
    # ===========================
    def action_open_field_tree_groups_wizard(self):
        self.ensure_one()
        return {
            'name': _('Crear Campo Dinámico'),
            'type': 'ir.actions.act_window',
            'res_model': 'field.tree.groups.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                # Pasamos el departamento/tablero actual para que el wizard lo detecte
                'default_board_id': self.department_id.id if self.department_id else False,
                'default_task_id': self.id,
            }
        }

    def action_open_delete_board_file_wizard(self):
        """Abre wizard para eliminar campos dinámicos"""
        self.ensure_one()
        return {
            'name': _('Eliminar Campo Dinámico'),
            'type': 'ir.actions.act_window',
            'res_model': 'delete.board.file.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_subtask_id': self.id,
                'default_board_id': self.department_id.id if self.department_id else False,
            }
        }

    def action_create_dynamic_field_wizard(self, field_name, field_label, field_type, field_info):
        """Método llamado desde el wizard para crear campos dinámicos"""
        self.ensure_one()

        valid_field_name = self._generate_valid_field_name(field_name)
        selection_values = self.env.context.get('selection_values', False)

        try:
            # 1. Crear el campo dinámico
            self._create_field_in_model(
                valid_field_name,
                field_label,
                field_type,
                selection_values
            )

            # 2. Actualizar la vista tree
            self._update_tree_view(valid_field_name, field_label)

            # 3. Verificar que la vista se creó correctamente
            department_identifier = f"board_{self.department_id.id}" if self.department_id else "global"
            view_created = self._verify_view_created(valid_field_name, department_identifier)

            if not view_created:
                _logger.warning("La vista no se creó automáticamente")
                self.env.cr.commit()
                raise UserError(_("La vista no se actualizó automáticamente. Por favor, actualice el módulo manualmente."))

            # 4. Almacenar metadata del campo
            self._store_field_metadata(valid_field_name, selection_values)

            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
                'params': {'wait': True}
            }

        except Exception as e:
            _logger.error("Field creation error: %s", str(e))
            raise UserError(_("Field creation failed: %s") % str(e))

    def _generate_valid_field_name(self, name):
        """Genera un nombre de campo válido"""
        clean_name = re.sub(r'[^a-zA-Z0-9_]', '', name.lower().replace(' ', '_'))
        if not clean_name.startswith('x_'):
            clean_name = f'x_{clean_name}'
        return clean_name

    def _create_field_in_model(self, field_name, field_label, field_type, selection_options=False):
        """Create technical field definition con soporte para selección"""
        model = self.env['ir.model'].sudo().search([('model', '=', self._name)])
        if not model:
            raise UserError(_("Model not found in system"))

        field_vals = {
            'name': field_name,
            'model_id': model.id,
            'field_description': field_label or field_name.replace('_', ' ').title(),
            'ttype': field_type,
            'state': 'manual',
            'store': True,
            'required': False,
        }

        if field_type == 'selection' and selection_options:
            field_vals['selection'] = selection_options

        self.env['ir.model.fields'].sudo().create(field_vals)
        self._add_column_to_table(field_name, field_type)

    def _add_column_to_table(self, field_name, field_type):
        """Add physical column to database"""
        type_mapping = {
            'char': 'varchar(255)',
            'integer': 'integer',
            'float': 'numeric(16,2)',
            'boolean': 'boolean',
            'date': 'date',
            'datetime': 'timestamp',
            'selection': 'varchar',
        }
        if field_type not in type_mapping:
            raise UserError(_("Unsupported field type: %s") % field_type)
        query = f"""
            ALTER TABLE {self._table} 
            ADD COLUMN IF NOT EXISTS {field_name} {type_mapping[field_type]}
        """
        self.env.cr.execute(query)

    def _store_field_metadata(self, field_name, selection_values=False):
        """Store field configuration JSON en task.board (registro actual)"""
        try:
            created_at = fields.Datetime.now()
            if hasattr(created_at, 'isoformat'):
                created_at = created_at.isoformat()
            
            field_data = {
                'name': field_name,
                'label': self.dynamic_field_label or field_name,
                'type': self.dynamic_field_type or 'char',
                'board_id': self.department_id.id if self.department_id else None,
                'created_at': created_at,
                'created_by': self.env.user.id,
            }
            
            if self.dynamic_field_type == 'selection' and selection_values:
                if isinstance(selection_values, str):
                    try:
                        selection_values = eval(selection_values)
                    except Exception:
                        selection_values = []
                field_data['options'] = selection_values
            
            current_data = {}
            if self.dynamic_fields_data:
                try:
                    current_data = json.loads(self.dynamic_fields_data)
                except json.JSONDecodeError:
                    current_data = {}
                    _logger.warning("Invalid JSON in dynamic_fields_data, resetting")
            
            current_data[field_name] = field_data
            self.dynamic_fields_data = json.dumps(current_data, default=str)
            
        except Exception as e:
            _logger.error("Metadata storage failed: %s", str(e))
            _logger.warning("Metadata no se pudo almacenar, pero el campo se creó exitosamente")

    def _get_tree_widget_for_field(self):
        """Get appropriate widget for field type"""
        widget_map = {
            'boolean': 'boolean',
            'selection': 'selection',
            'date': 'daterange',
            'datetime': 'datetime',
            'float': 'float',
            'integer': 'integer',
        }
        widget = widget_map.get(self.dynamic_field_type, '')
        return f'widget="{widget}"' if widget else ''

    def _update_tree_view(self, field_name, field_label):
        """Actualiza la vista tree SOLO para el tablero actual usando el ID del tablero."""
        self.ensure_one()
        try:
            # Obtener la vista tree base
            tree_view = self.env.ref('task_planner.activity_planner_task_view_tree', raise_if_not_found=False)
            if not tree_view:
                raise UserError(_("No se encontró la vista tree base"))

            widget_info = self._get_tree_widget_for_field()

            # Obtener el ID del tablero actual para usar en el contexto
            board_id = self.department_id.id if self.department_id else False
            if not board_id:
                raise UserError(_("No se pudo determinar el ID del tablero para asociar el campo."))

            # Generar XML con condición basada en el ID del tablero en el contexto
            arch_base = f"""
            <data>
                <xpath expr="//field[@name='completed_subtasks']" position="after">
                    <field name="{field_name}" string="{field_label}" {widget_info}
                        optional="show"
                        invisible="context.get('default_department_id') != {board_id} or not context.get('default_department_id')"
                    />
                </xpath>
            </data>
            """

            # Validar XML
            try:
                etree.fromstring(arch_base)
            except etree.XMLSyntaxError as e:
                raise UserError(_("Error en la estructura XML: %s") % str(e))

            # Eliminar vistas existentes para este campo y tablero específico
            view_pattern = f"task.board.tree.dynamic.{field_name}.board_{board_id}"
            existing_views = self.env['ir.ui.view'].search([
                ('name', '=', view_pattern),
                ('model', '=', 'task.board')
            ])
            if existing_views:
                existing_views.unlink()

            # Crear la nueva vista dinámica específica para este tablero
            self.env['ir.ui.view'].create({
                'name': view_pattern,
                'model': 'task.board',
                'arch_base': arch_base,
                'inherit_id': tree_view.id,
                'type': 'tree',
                'priority': 100,
            })

            # Limpiar cache
            self.env['ir.ui.view'].clear_caches()

            # Forzar la regeneración de vistas
            self._ultimate_cache_cleanup()

            return True

        except Exception as e:
            _logger.error("Error updating tree view: %s", str(e))
            raise UserError(_("Error actualizando la vista tree: %s") % str(e))

    def get_action_with_board(self, board_id):
        """Devuelve una acción 'act_window' para task.board asegurando board_id en el context"""
        action = self.env['ir.actions.act_window'].search([
            ('res_model', '=', 'task.board')
        ], limit=1)

        if not action:
            try:
                action = self.env.ref('task_planner.action_task_board')
            except Exception:
                raise UserError(_("No se encontró una acción para abrir task.board."))

        action_data = action.read()[0]

        # Asegurar que el contexto es un diccionario
        ctx = action_data.get('context', {})
        if isinstance(ctx, str):
            try:
                ctx = eval(ctx) if ctx else {}
            except Exception:
                ctx = {}

        # Agregar el board_id al contexto
        ctx['board_id'] = board_id
        action_data['context'] = ctx

        return action_data

    def _force_module_update(self):
        try:
            module = self.env['ir.module.module'].search([('name', '=', 'task_planner')], limit=1)
            if module:
                module.button_immediate_upgrade()
                _logger.info("Módulo actualizado forzadamente")
            else:
                _logger.warning("No se encontró el módulo task_planner para actualizar")
        except Exception as e:
            _logger.error("Error actualizando módulo: %s", str(e))

    # --------------------------------------------
    # FIELD REMOVAL METHODS
    # --------------------------------------------
    def _get_existing_dynamic_fields(self):
        """Obtiene campos dinámicos SOLO del tablero actual (department_id)"""
        ORIGINAL_FIELDS = {
            'name', 'sequence', 'completion_date', 'department_id', 'person', 
            'allowed_member_ids', 'state', 'color', 'files', 'show_subtasks',
            'subtask_ids', 'subtasks_count', 'completed_subtasks', 'total_subtasks',
            'progress', 'apply_to_specific_task', 'dynamic_field_name', 
            'dynamic_field_label', 'dynamic_field_type', 'selection_options',
            'dynamic_fields_data', 'dynamic_field_list', 'has_dynamic_fields'
        }

        dynamic_fields = []
        if self.dynamic_fields_data:
            try:
                field_data = json.loads(self.dynamic_fields_data)
                for field_name, config in field_data.items():
                    if (isinstance(config, dict) and 
                        config.get('board_id') == (self.department_id.id if self.department_id else None) and
                        field_name not in ORIGINAL_FIELDS):

                        field_obj = self.env['ir.model.fields'].search([
                            ('model', '=', self._name),
                            ('name', '=', field_name)
                        ], limit=1)

                        if field_obj:
                            dynamic_fields.append(field_obj)
            except json.JSONDecodeError:
                pass

        return dynamic_fields

    def _get_dynamic_field_options(self):
        dynamic_fields = self._get_existing_dynamic_fields()
        return [(field.name, field.field_description) for field in dynamic_fields]

    def action_remove_dynamic_field(self):
        self.ensure_one()
        dynamic_fields = self._get_existing_dynamic_fields()

        if not dynamic_fields:
            raise UserError(_("No hay campos dinámicos adicionales para eliminar"))

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
        self.ensure_one()
        if not self.dynamic_field_to_remove:
            raise UserError(_("Por favor seleccione un campo para eliminar"))

        field_name = self.dynamic_field_to_remove
        
        try:
            self._ultimate_cache_cleanup()
            self._remove_all_field_views(field_name)
            self._remove_field_definition(field_name)
            self._remove_field_metadata(field_name)
            self._safe_remove_column(field_name)

            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
                'params': {'wait': True}
            }
        except Exception as e:
            _logger.error("Error removing field %s: %s", field_name, str(e))
            raise UserError(_("Error eliminando campo: %s") % str(e))

    def _remove_all_field_views(self, field_name):
        """Elimina todas las vistas relacionadas con el campo por departamento(tablero)"""
        try:
            board_id = self.department_id.id if self.department_id else False
            view_pattern = f"{self._name}.tree.dynamic.{field_name}.board_{board_id or 'global'}"
            self.env['ir.ui.view'].search([
                ('name', '=', view_pattern),
                ('model', '=', self._name)
            ]).unlink()
        except Exception as e:
            _logger.error("Error removing field views: %s", str(e))

    def _remove_field_artifacts(self, field_name):
        try:
            views = self.env['ir.ui.view'].search([
                ('name', 'like', f'{self._name}.tree.dynamic.{field_name}%'),
                ('model', '=', self._name)
            ])
            if views:
                views.unlink()
            self._remove_field_metadata(field_name)
            
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

            self._safe_remove_column(field_name)
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
                        task.dynamic_fields_data = False
        except Exception as e:
            _logger.error("Error removing field metadata: %s", str(e))
            raise
    
    def _remove_field_definition(self, field_name):
        """Elimina la definición del campo de manera robusta"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                field = self.env['ir.model.fields'].sudo().search([
                    ('model', '=', self._name),
                    ('name', '=', field_name)
                ], limit=1)

                if field:
                    self.env['ir.translation'].sudo().search([
                        ('name', '=', 'ir.model.fields,field_description'),
                        ('res_id', '=', field.id)
                    ]).unlink()

                    field.unlink()

                    if self.env['ir.model.fields'].sudo().search([('id', '=', field.id)], count=True):
                        raise Exception("Field still exists after unlink")

                    return True

                return False

            except Exception as e:
                if attempt == max_attempts - 1:
                    _logger.error("Failed to remove field definition after %s attempts: %s", max_attempts, str(e))
                    self.env.cr.execute("""
                        DELETE FROM ir_model_fields
                        WHERE model = %s AND name = %s
                    """, [self._name, field_name])
                    self.env.cr.commit()
                else:
                    time.sleep(0.5 * (attempt + 1))
    
    def _safe_remove_column(self, field_name):
        """Safely remove column from database"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                self.env.cr.execute("BEGIN;")

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

    def _verify_view_created(self, field_name, board_identifier):
        """Verifica que la vista se haya creado correctamente"""
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                created_view = self.env['ir.ui.view'].search([
                    ('name', '=', f'task.board.tree.dynamic.{field_name}.{board_identifier}'),
                    ('model', '=', 'task.board')
                ], limit=1)
                if created_view:
                    try:
                        etree.fromstring(created_view.arch_base)
                        _logger.info("Vista creada y validada exitosamente: %s", created_view.name)
                        arch_str = created_view.arch_base
                        if field_name in arch_str:
                            return True
                        else:
                            _logger.warning("Campo no encontrado en la vista (intento %d)", attempt + 1)
                    except etree.XMLSyntaxError as e:
                        _logger.warning("Vista con XML inválido (intento %d): %s", attempt + 1, str(e))
                else:
                    _logger.warning("Vista no encontrada (intento %d)", attempt + 1)
                time.sleep(1)
            except Exception as e:
                _logger.error("Error verificando vista: %s", str(e))
                time.sleep(1)
        return False

    # --------------------------------------------
    # CACHE METHODS
    # --------------------------------------------
    def _ultimate_cache_cleanup(self):
        """Limpieza de caché más completa y efectiva - Versión corregida"""
        try:
            self.env.invalidate_all()
            if hasattr(self.env.registry, '_clear_cache'):
                self.env.registry._clear_cache()
            if hasattr(self.env.registry, '_clear_view_cache'):
                self.env.registry._clear_view_cache()
            self.env.registry.setup_models(self.env.cr)
            self.env['ir.ui.view'].clear_caches()
            if self._name in self.env.registry.models:
                self.env.registry.init_models(self.env.cr, [self._name], {'module': self._module or 'task_planner'})
            _logger.info("Limpieza de caché completada exitosamente")
        except Exception as e:
            _logger.error("Error en limpieza completa de caché: %s", str(e))
            raise UserError(_("Error en limpieza de caché: %s") % str(e))
    
    def _regenerate_assets_safely(self):
        try:
            self.env['ir.module.module'].update_list()
            domain = [
                ("res_model", "=", "ir.ui.view"),
                "|",
                ("name", "=like", "%.assets_%.css"),
                ("name", "=like", "%.assets_%.js")
            ]
            asset_attachments = self.env['ir.attachment'].search(domain)
            if asset_attachments:
                asset_attachments.unlink()
                _logger.info("Eliminados %d attachments de assets obsoletos", len(asset_attachments))
        except Exception as e:
            _logger.warning("No se pudieron regenerar assets: %s", str(e))
     
    def _clean_asset_attachments(self):
        try:
            domain = [
                ("res_model", "=", "ir.ui.view"),
                "|",
                ("name", "=like", "%.assets_%.css"),
                ("name", "=like", "%.assets_%.js")
            ]
            asset_attachments = self.env['ir.attachment'].search(domain)
            if asset_attachments:
                asset_attachments.unlink()
                _logger.info("Eliminados %d attachments de assets obsoletos", len(asset_attachments))
        except Exception as e:
            _logger.error("Error limpiando assets: %s", str(e))

    # --------------------------------------------
    # ACTION METHODS
    # --------------------------------------------
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
        for task in self:
            task.show_subtasks = not task.show_subtasks
        return True
    
    def open_details_form(self):
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

    def action_save(self):
        return True

    def _get_previous_state(self):
        if self.progress >= 100:
            return 'done'
        elif self.progress > 0:
            return 'in_progress'
        return 'new'

    # --------------------------------------------
    # CONSTRAINTS AND VALIDATION
    # --------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record._check_required_fields()
        return records

    def write(self, vals):
        result = super().write(vals)
        for record in self:
            record._check_required_fields()
        return result

    @api.constrains('name', 'person', 'department_id')
    def _check_required_fields(self):
        for record in self:
            if not record.name:
                raise ValidationError(_("El nombre de la tarea es obligatorio"))
            if not record.person:
                raise ValidationError(_("Debe asignar un responsable"))
            if not record.department_id:
                raise ValidationError(_("Debe seleccionar un tablero"))

            # Verificar si department_id existe antes de acceder a sus atributos
            if record.department_id:
                if (record.department_id.pick_from_dept and 
                    record.person.id not in record.department_id.member_ids.ids):
                    raise ValidationError(_(
                        "El empleado %s no está en la lista de miembros permitidos del tablero %s. "
                        "Verifica la asignación."
                    ) % (record.person.name, record.department_id.name))
