from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from .boards import STATES
import logging
import json
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
    name = fields.Char(string='Task Name', required=True, tracking=True)
    completion_date = fields.Datetime(string="Timeline")
    drag = fields.Integer()
    files = fields.Many2many('ir.attachment', string="Files")
    state = fields.Selection(STATES, default="new", string="Status", tracking=True)
    field_info = fields.Text(string="Ingresar datos para el campo") 
    
    # Relational fields
    task_id = fields.Many2one('task.board', string='Parent Task', ondelete='cascade')
    person = fields.Many2one(
        'hr.employee', 
        string='Assigned To',
        tracking=True,
        domain="[('id', 'in', allowed_member_ids)]"
    )
    activity_line_ids = fields.One2many('subtask.activity', 'subtask_id', string='Activities')
    
    # Dynamic fields management
    dynamic_field_name = fields.Char(string="Technical Name")
    dynamic_field_label = fields.Char(string="Display Label")
    dynamic_field_type = fields.Selection([
        ('char', 'Text'),
        ('integer', 'Integer'),
        ('float', 'Decimal'),
        ('boolean', 'Boolean'),
        ('date', 'Date'),
        ('datetime', 'Datetime'),
        ('selection', 'Selection')],
        string="Field Type"
    )
    selection_options = fields.Text(
        string="Selection Options",
        help="Format: key:value\none per line"
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

    # ===========================
    # COMPUTED METHODS
    # ===========================

    def _compute_has_dynamic_fields(self):
        """Actualización optimizada del campo computado"""
        dynamic_count = self.env['ir.model.fields'].search_count([
            ('model', '=', self._name),
            ('name', 'like', 'x_%'),
            ('state', '=', 'manual')
        ])
        for record in self:
            record.has_dynamic_fields = bool(dynamic_count)

    @api.constrains('person', 'task_id')
    def _check_person_selection(self):
        for subtask in self:
            if (subtask.task_id and subtask.task_id.department_id and 
                subtask.person and subtask.person.id not in subtask.task_id.department_id.member_ids.ids):
                raise ValidationError(
                    _("The assigned employee must be a member of the parent task's department")
                )

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
        """Método para crear campos dinámicos"""
        if not all([self.dynamic_field_name, self.dynamic_field_type]):
            raise UserError(_("Field name and type are required"))
    
        field_name = self._generate_valid_field_name(self.dynamic_field_name)
        field_label = self.dynamic_field_label or self.dynamic_field_name.replace('_', ' ').title()
    
        try:
            # 1. Crear el campo dinámico
            self._create_field_in_model(
                field_name,
                field_label,
                self.dynamic_field_type,
                self.selection_options
            )
    
            # 2. Actualizar TODAS las subtareas existentes
            all_subtasks = self.env['subtask.board'].search([])
            
            if self.field_info:
                if self.dynamic_field_type == 'selection' and self.selection_options:
                    options = [line.split(':')[0].strip() 
                             for line in self.selection_options.split('\n') 
                             if line.strip()]
                    if options:
                        all_subtasks.write({field_name: options[0]})
                else:
                    all_subtasks.write({field_name: self.field_info})
    
            # 3. Actualizar la vista
            self._update_tree_view(field_name, field_label)
            self._store_field_metadata(field_name)
    
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

    def _create_field_in_model(self, field_name, field_label, field_type, selection_options=None):
        """Create technical field definition"""
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
            selection = []
            for line in selection_options.split('\n'):
                if line.strip() and ':' in line:
                    key, val = map(str.strip, line.split(':', 1))
                    selection.append((key, val))
            if selection:
                field_vals['selection'] = str(selection)

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

    def _update_tree_view(self, field_name, field_label):
        """Actualiza la vista tree de subtask.board"""
        try:
            view = self.env.ref('task_planner.view_subtask_tree', raise_if_not_found=False)
            if not view:
                raise UserError(_("No se encontró la vista 'task_planner.view_subtask_tree'"))

            widget_info = self._get_tree_widget_for_field() or ""

            arch = f"""
            <data>
                <xpath expr="//field[@name='files']" position="after">
                    <field name="{field_name}" string="{field_label}" {widget_info}
                           optional="show"
                           invisible="context.get('default_task_id') != {self.task_id.id} or not context.get('default_task_id')"/>
                </xpath>
            </data>
            """

            existing_view = self.env['ir.ui.view'].search([
                ('name', '=', f'subtask.board.tree.dynamic.{field_name}.{self.task_id.id}'),
                ('model', '=', 'subtask.board')
            ])

            if existing_view:
                existing_view.unlink()

            self.env['ir.ui.view'].create({
                'name': f'subtask.board.tree.dynamic.{field_name}.{self.task_id.id}',
                'model': 'subtask.board',
                'inherit_id': view.id,
                'arch': arch,
                'type': 'tree',
                'priority': 100,
            })

            self.env['ir.ui.view'].clear_caches()
            _logger.info("✅ Vista tree actualizada con campo %s para tarea %s", field_name, self.task_id.id)

        except Exception as e:
            _logger.error("❌ Error actualizando la vista: %s", str(e))
            raise UserError(_("Error al actualizar la vista. Consulte los logs."))

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

    def _store_field_metadata(self, field_name):
        """Store field configuration in JSON"""
        try:
            field_data = {
                'name': field_name,
                'label': self.dynamic_field_label,
                'type': self.dynamic_field_type,
                'created_at': fields.Datetime.now(),
                'created_by': self.env.user.id,
            }
      
            if self.dynamic_field_type == 'selection' and self.selection_options:
                field_data['options'] = self.selection_options
      
            current_data = {}
            if self.dynamic_fields_data:
                try:
                    current_data = json.loads(self.dynamic_fields_data)
                except:
                    current_data = {}
      
            current_data[field_name] = field_data
            self.dynamic_fields_data = json.dumps(current_data)
      
        except Exception as e:
            _logger.error("Metadata storage failed: %s", str(e))

    # ===========================
    # VIEW METHODS
    # ===========================

    @api.model
    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        res = super(SubtaskBoard, self).fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu
        )

        if view_type == 'form':
            dynamic_fields = self.env['ir.model.fields'].search([
                ('model', '=', self._name),
                ('name', 'like', 'x_%'),
                ('state', '=', 'manual')
            ])

            if dynamic_fields:
                doc = etree.XML(res['arch'])

                # Buscar el grupo de campos dinámicos
                for group_node in doc.xpath("//group[@string='Campos Personalizados']"):
                    # Limpiar el grupo antes de añadir nuevos campos
                    group_node.clear()

                    # Añadir cada campo dinámico con su configuración adecuada
                    for field in dynamic_fields:
                        field_attrs = {
                            'name': field.name,
                            'string': field.field_description,
                            'optional': 'show'
                        }

                        # Widgets específicos por tipo de campo
                        if field.ttype == 'selection':
                            field_attrs['widget'] = 'selection'
                        elif field.ttype == 'boolean':
                            field_attrs['widget'] = 'boolean'
                        elif field.ttype == 'date':
                            field_attrs['widget'] = 'date'
                        elif field.ttype == 'datetime':
                            field_attrs['widget'] = 'datetime'

                        field_node = etree.Element('field', field_attrs)
                        group_node.append(field_node)

                res['arch'] = etree.tostring(doc, encoding='unicode')

        return res

    