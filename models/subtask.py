from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from .boards import STATES
import logging
import json
from datetime import datetime
import re
from psycopg2.extensions import AsIs
from datetime import datetime
from lxml import etree

_logger = logging.getLogger(__name__)

class SubtaskBoard(models.Model):
    _name = 'subtask.board'
    _description = 'Subtarea del Planificador de Actividades'
    _inherit = ['mail.thread']
    
    # ===========================
    # FIELD DEFINITIONS
    # ===========================
    
    # Basic fields
    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Nombre de la Tarea', required=True, tracking=True)
    completion_date = fields.Datetime(string="Timeline")
    drag = fields.Integer()
    files = fields.Many2many('ir.attachment', string="Archivos")
    state = fields.Selection(STATES, default="new", string="Estado", tracking=True)
    field_info = fields.Text(string="Ingresar datos para el campo") 
    progress = fields.Integer(string="Progreso")
    completed_subtasks = fields.Integer(string="Subtareas Completadas")
    total_subtasks = fields.Integer(string="Total de Subtareas")
    
    # Relational fields
    task_id = fields.Many2one('task.board', string='Parent Task', ondelete='cascade')
    person = fields.Many2one(
        'hr.employee', 
        string='Responsable',
        tracking=True,
        domain="[('id', 'in', allowed_member_ids)]"
    )
    activity_line_ids = fields.One2many('subtask.activity', 'subtask_id', string='Actividades')
    
    # Dynamic fields management
    dynamic_field_name = fields.Char(string="Technical Name")
    dynamic_field_label = fields.Char(string="Display Label")
    dynamic_field_type = fields.Selection([
        ('char', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Decimal'),
        ('boolean', 'Boolean'),
        ('date', 'Date'),
        ('selection','Selection'),
        ('datetime', 'Datetime'),
        ],
        string="Field Type"
    )
    
    dynamic_fields_data = fields.Text(
        string="Fields Configuration",
        help="Stores configuration in JSON format"
    )
    
    # Computed/related fields
    allowed_member_ids = fields.Many2many(
        'hr.employee',
        string='Allowed Members',
        related='task_id.allowed_member_ids',
        readonly=True
    )

    has_dynamic_fields = fields.Boolean(
        string="Has Dynamic Fields",
        compute='_compute_has_dynamic_fields',
        store=False
    )

    department_id = fields.Many2one('hr.department', string='Departamento', compute='_compute_department_id', store=True)

    min_sequence = fields.Integer(
    compute='_compute_min_sequence',
    store=False,
    string="Sequence Mínimo"
    )
    sequence = fields.Integer(string="Secuencia", default=1, required=True)
    
    sequence_number = fields.Integer(
    string='Nº Secuencial',
    readonly=True,
    copy=False,
    help='Número secuencial automático para cada registro'
    )

    @api.model_create_multi
    def create(self, vals_list):
        # Buscar si ya existe un registro con sequence_number = 1
        existing_record = self.search([('sequence_number', '=', 1)], limit=1)

        # Si no existe ningún registro con sequence_number = 1
        if not existing_record:
            # Asignar el valor 1 al primer registro de la lista
            if vals_list:
                vals_list[0]['sequence_number'] = 1

            # Procesar el resto de registros con numeración secuencial normal
            if len(vals_list) > 1:
                max_sequence = self.search([], order='sequence_number desc', limit=1).sequence_number or 0
                for vals in vals_list[1:]:
                    max_sequence += 1
                    vals['sequence_number'] = max_sequence
        else:
            # Numeración secuencial normal (cuando ya existe el registro con valor 1)
            max_sequence = self.search([], order='sequence_number desc', limit=1).sequence_number or 0
            for vals in vals_list:
                max_sequence += 1
                vals['sequence_number'] = max_sequence 
        return super(SubtaskBoard, self).create(vals_list)

    @api.depends('person')
    def _compute_department_id(self):
        for record in self:
            record.department_id = record.person.department_id.id if record.person else False

    def _compute_has_dynamic_fields(self):
        """Actualización optimizada del campo computado"""
        dynamic_count = self.env['ir.model.fields'].search_count([
            ('model', '=', self._name),
            ('name', 'like', 'x_%'),
            ('state', '=', 'manual')
        ])
        for record in self:
            record.has_dynamic_fields = bool(dynamic_count)

    
    # ===========================
    # ACTION METHODS
    # ===========================

    def open_activities_action(self):
        self.ensure_one()
        return {
            'name': _('Actividades de %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'subtask.activity',
            'view_mode': 'form',
            'domain': [('subtask_id', '=', self.id)],
            'context': {
                'default_subtask_id': self.id,
                'default_person': self.person.id if self.person else False,
                'search_default_subtask_id': self.id
            },
            'target': 'current',
        }

    def action_open_activity_tree(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'subtask.activity',
            'view_mode': 'tree,form',
            'target': 'current',
            'domain': [('subtask_id', '=', self.id)],
            'context': {
                'default_subtask_id': self.id,
                'search_default_subtask_id': self.id
            },
            'name': _('Activities for %s') % self.name
        }

    def action_custom_create_subtask(self):
        if not self.task_id:
            raise UserError(_("A parent task is required to create subtasks"))
    
        defaults = {
            'task_id': self.task_id.id,
            'name': _("Subtask for %s") % self.task_id.name,
        }
    
        if hasattr(self.task_id, 'allowed_member_ids'):
            defaults['allowed_member_ids'] = [(6, 0, self.task_id.allowed_member_ids.ids)]
    
        return {
            'name': _('New Subtask'),
            'type': 'ir.actions.act_window',
            'res_model': 'subtask.board',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_' + key: value for key, value in defaults.items()
            }
        }

    def action_open_dynamic_field_wizard(self):
        self.ensure_one()
        return {
            'name': _('Create Dynamic Field'),
            'type': 'ir.actions.act_window',
            'res_model': 'dynamic.field.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref('task_planner.view_dynamic_field_wizard_form').id,
            'target': 'new',
            'context': {
                'default_subtask_id': self.id,
            }
        }
        
    def action_open_delete_field_wizard(self):
        """Abre wizard para eliminar campos dinámicos"""
        self.ensure_one()
        return {
            'name': _('Eliminar Campo Dinámico'),
            'type': 'ir.actions.act_window',
            'res_model': 'delete.dynamic.field.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_subtask_id': self.id,
            }
        }

    def action_open_dynamic_fields_form(self):
        """Abre el formulario emergente para editar campos dinámicos"""
        return {
            "type": "ir.actions.act_window",
            "name": "Editar Campos Dinámicos",
            "res_model": "subtask.board",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref("task_planner.view_subtask_dynamic_fields_form").id,
            "target": "new",
            "flags": {"form": {"action_buttons": True}},
        }

    # ===========================
    # DYNAMIC FIELD CREATION METHODS
    # ===========================

    def action_create_dynamic_field(self):
        """Método para crear campos dinámicos con soporte para selección"""
        self.ensure_one()
        if not all([self.dynamic_field_name, self.dynamic_field_type]):
            raise UserError(_("Field name and type are required"))

        field_name = self._generate_valid_field_name(self.dynamic_field_name)
        field_label = self.dynamic_field_label or self.dynamic_field_name.replace('_', ' ').title()

        # Obtener opciones de selección del contexto si existen
        selection_values = self.env.context.get('selection_values', False)

        try:
            # 1. Crear el campo dinámico
            self._create_field_in_model(
                field_name,
                field_label,
                self.dynamic_field_type,
                selection_values  # Pasar las opciones de selección
            )

            # 2. Actualizar TODAS las subtareas existentes
            all_subtasks = self.env['subtask.board'].search([])

            # 3. Actualizar la vista
            self._update_tree_view(field_name, field_label)
            self._store_field_metadata(field_name, selection_values)

            return {'type': 'ir.actions.client', 'tag': 'reload'}

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

        # Para campos de selección, añadir las opciones
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
        self._cr.execute(query)

    def _store_field_metadata(self, field_name, selection_values=False):
        """Store field configuration in JSON incluyendo opciones de selección"""
        try:
            field_data = {
                'name': field_name,
                'label': self.dynamic_field_label,
                'type': self.dynamic_field_type,
                'created_at': datetime.now().isoformat(),  # Convertir a string ISO
                'created_by': self.env.user.id,
            }
            
            # Resto del código de serialización...
            current_data = {}
            if self.dynamic_fields_data:
                try:
                    current_data = json.loads(self.dynamic_fields_data)
                except json.JSONDecodeError:
                    current_data = {}
            
            current_data[field_name] = field_data
            self.dynamic_fields_data = json.dumps(current_data)
            
        except Exception as e:
            _logger.error("Metadata storage failed: %s", str(e))
            raise UserError(_("Error storing field metadata: %s") % str(e))

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
        """Actualiza la vista tree y form de subtask.board"""
        try:
            # Obtener las vistas
            tree_view = self.env.ref('task_planner.view_subtask_tree', raise_if_not_found=False)
            form_view = self.env.ref('task_planner.activity_planner_subtask_form', raise_if_not_found=False)
            
            if not tree_view:
                raise UserError(_("No se encontró la vista 'task_planner.view_subtask_tree'"))
            if not form_view:
                raise UserError(_("No se encontró la vista 'task_planner.activity_planner_subtask_form'"))
    
            widget_info = self._get_tree_widget_for_field() or ""
    
            # Arch XML para la vista tree
            tree_arch = f"""
            <data>
                <xpath expr="//field[@name='files']" position="after">
                    <field name="{field_name}" string="{field_label}" {widget_info}
                           optional="show"
                           invisible="context.get('default_task_id') != {self.task_id.id} or not context.get('default_task_id')"/>
                </xpath>
            </data>
            """
    
            # Arch XML para la vista form
            form_arch = f"""
            <data>
                <xpath expr="//field[@name='files']" position="after">
                    <field name="{field_name}" string="{field_label}"
                           invisible="context.get('default_task_id') != {self.task_id.id} or not context.get('default_task_id')"/>
                </xpath>
            </data>
            """
    
            # Eliminar vistas existentes si las hay
            existing_tree_view = self.env['ir.ui.view'].search([
                ('name', '=', f'subtask.board.tree.dynamic.{field_name}.{self.task_id.id}'),
                ('model', '=', 'subtask.board')
            ])
            existing_form_view = self.env['ir.ui.view'].search([
                ('name', '=', f'subtask.board.form.dynamic.{field_name}.{self.task_id.id}'),
                ('model', '=', 'subtask.board')
            ])
    
            if existing_tree_view:
                existing_tree_view.unlink()
            if existing_form_view:
                existing_form_view.unlink()
    
            # Crear vista tree
            self.env['ir.ui.view'].create({
                'name': f'subtask.board.tree.dynamic.{field_name}.{self.task_id.id}',
                'model': 'subtask.board',
                'arch': tree_arch,
                'inherit_id': tree_view.id,
                'type': 'tree',
                'priority': 100,
            })
    
            # Crear vista form
            self.env['ir.ui.view'].create({
                'name': f'subtask.board.form.dynamic.{field_name}.{self.task_id.id}',
                'model': 'subtask.board',
                'arch': form_arch,
                'inherit_id': form_view.id,
                'type': 'form',
                'priority': 100,
            })
    
        except Exception as e:
            _logger.error("Error updating views: %s", str(e))
            raise UserError(_("Error updating views: %s") % str(e))
    