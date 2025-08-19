from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from .boards import STATES
import logging
import json
import re
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
    dynamic_field_to_delete = fields.Many2one(
        'ir.model.fields',
        string="Field to Delete",
        domain="[('model', '=', 'subtask.board'), ('state', '=', 'manual')]"
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
        store=False  # No necesitamos almacenarlo, se calcula dinámicamente
    )

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
            'target': 'current',  # Puedes usar 'new' para un popup
        }

    def _compute_has_dynamic_fields(self):
        """Actualización optimizada del campo computado"""
        dynamic_count = self.env['ir.model.fields'].search_count([
            ('model', '=', self._name),
            ('name', 'like', 'x_%'),
            ('state', '=', 'manual')
        ])
        for record in self:
            record.has_dynamic_fields = bool(dynamic_count)

    def force_view_update(self):
        """Método para forzar la actualización de vistas"""
        view = self.env.ref('tu_modulo.view_subtask_board_form')
        view.write({'arch': view.arch})
        self.env['ir.ui.view'].clear_caches()
        return True

    def _generate_valid_field_name(self, name):
        """Genera un nombre de campo válido sin forzar 'x_' para campos de sistema"""
        # Limpia el nombre: solo letras, números y guiones bajos
        clean_name = re.sub(r'[^a-zA-Z0-9_]', '', name.lower().replace(' ', '_'))
        
        # Si el campo es para ir.model.fields (como task_board_id), no añadir 'x_'
        if self._context.get('is_system_field'):
            return clean_name
        
        # Para campos dinámicos en otros modelos, mantener la lógica original
        if not clean_name.startswith('x_'):
            clean_name = f'x_{clean_name}'
        return clean_name

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

    @api.depends()
    def _compute_dynamic_fields_data(self):
        """Devuelve los campos dinámicos como JSON string"""
        for record in self:
            try:
                dynamic_fields = [
                    {'name': name, 'string': self._fields[name].string or name}
                    for name in self._fields
                    if name.startswith(('x_', 'dynamic_', 'custom_'))
                ]
                record.dynamic_fields_data = json.dumps(dynamic_fields or [])
            except Exception:
                record.dynamic_fields_data = '[]'

    def get_converted_value(self):
        self.ensure_one()
        try:
            if self.dynamic_field_type == 'integer':
                return int(self.dynamic_field_value) if self.dynamic_field_value else 0
            elif self.dynamic_field_type == 'float':
                return float(self.dynamic_field_value) if self.dynamic_field_value else 0.0
            elif self.dynamic_field_type == 'boolean':
                return bool(self.dynamic_field_value.lower() == 'true') if self.dynamic_field_value else False
            elif self.dynamic_field_type == 'date':
                return fields.Date.from_string(self.dynamic_field_value) if self.dynamic_field_value else False
            elif self.dynamic_field_type == 'datetime':
                return fields.Datetime.from_string(self.dynamic_field_value) if self.dynamic_field_value else False
            else:  # char, selection y otros
                return self.dynamic_field_value or ''
        except (ValueError, AttributeError):
            raise UserError(_("El valor no coincide con el tipo de campo"))

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

    def action_open_dynamic_fields_form(self):
        """Abre el formulario emergente para editar campos dinámicos"""
        return {
            "type": "ir.actions.act_window",
            "name": "Editar Campos Dinámicos",
            "res_model": "subtask.board",  # Mismo modelo (no wizard)
            "res_id": self.id,  # ID del registro actual
            "view_mode": "form",
            "view_id": self.env.ref("task_planner.view_subtask_dynamic_fields_form").id,
        "target": "new",  # Abre en ventana emergente
        "flags": {"form": {"action_buttons": True}},
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

    def action_create_dynamic_field(self):
        """Método modificado para trabajar directamente desde subtask.board"""
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
            
            if self.field_info:  # Si hay información para guardar
                # Para campos de selección, necesitamos el valor clave (no el label)
                if self.dynamic_field_type == 'selection' and self.selection_options:
                    options = [line.split(':')[0].strip() 
                             for line in self.selection_options.split('\n') 
                             if line.strip()]
                    if options:
                        all_subtasks.write({field_name: options[0]})  # Usa la primera opción
                else:
                    all_subtasks.write({field_name: self.field_info})
    
            # 3. Actualizar la vista
            self._update_tree_view(field_name, field_label)
            self._store_field_metadata(field_name)
    
            return {'type': 'ir.actions.client', 'tag': 'reload'}
    
        except Exception as e:
            _logger.error("Field creation error: %s", str(e))
            raise UserError(_("Field creation failed: %s") % str(e))

    def action_delete_dynamic_field(self):
        self.ensure_one()

        if not self.dynamic_field_to_delete:
            raise UserError(_("Please select a field to delete"))

        try:
            field_name = self.dynamic_field_to_delete.name
            self._remove_column_from_table(field_name)
            self.dynamic_field_to_delete.unlink()
            self._clean_field_metadata(field_name)
            self._remove_field_from_views(field_name)
            
            # Clear selection after deletion
            self.dynamic_field_to_delete = False
            
            return {'type': 'ir.actions.client', 'tag': 'reload'}

        except Exception as e:
            _logger.error("Field deletion error: %s", str(e))
            raise UserError(_("Field deletion failed: %s") % str(e))

    def cleanup_orphan_fields(self):
        """Clean up orphaned dynamic fields"""
        self._cr.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = %s 
            AND column_name LIKE 'x_%'
        """, [self._table])
        
        for col in [r[0] for r in self._cr.fetchall()]:
            if not hasattr(self, col):
                _logger.info("Cleaning up orphaned field %s", col)
                self._cr.execute(f"ALTER TABLE {self._table} DROP COLUMN IF EXISTS {col}")

    # ===========================
    # DYNAMIC FIELD UTILITIES
    # ===========================

    def _generate_valid_field_name(self, name):
        """Generate valid Odoo field name"""
        name = re.sub(r'[^a-zA-Z0-9_]', '', name.lower().replace(' ', '_'))
        if not name.startswith('x_'):
            name = f'x_{name}'
        if len(name) > 2 and name[2].isdigit():
            name = f'x_field_{name[2:]}'
        return name

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
        """Update tree view to show new field with the info"""
        try:
            view = self.env.ref('task_planner.view_subtask_tree')
            arch = f"""
            <data>
                <xpath expr="//tree" position="inside">
                    <field name="{field_name}" string="{field_label}" 
                           optional="show" {self._get_tree_widget_for_field()}  invisible="context.get('name') != {self.name}"/>
                </xpath>
            </data>
            """

            self.env['ir.ui.view'].create({
                'name': f'subtask.board.tree.dynamic.{field_name}',
                'model': self._name,
                'inherit_id': view.id,
                'arch': arch,
                'type': 'tree',
                'priority': 99,
            })

            self.env['ir.ui.view'].clear_caches()
        except Exception as e:
            _logger.error("View update failed: %s", str(e))
            raise

    def action_open_delete_field_wizard(self):
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
    
    def _remove_field_from_all_views(self, field_name):
        """Elimina el campo de todas las vistas donde aparezca"""
        try:
            # Busca y elimina el campo de todas las vistas
            View = self.env['ir.ui.view']
            views = View.search([
                ('model', '=', self._name),
                ('arch_db', 'like', field_name)
            ])

            for view in views:
                try:
                    arch = etree.fromstring(view.arch_db)
                    for node in arch.xpath(f"//field[@name='{field_name}']"):
                        parent = node.getparent()
                        if parent is not None:
                            parent.remove(node)
                    view.write({'arch_db': etree.tostring(arch)})
                except Exception as e:
                    _logger.warning(f"No se pudo actualizar vista {view.id}: {str(e)}")
                    continue

        except Exception as e:
            _logger.error(f"Error limpiando vistas: {str(e)}")
            raise
    
    def safe_delete_dynamic_field(self, field_name):
        """Eliminación más segura con verificación paso a paso"""
        try:
            # Verifica si el campo existe
            field = self.env['ir.model.fields'].search([
                ('model', '=', self._name),
                ('name', '=', field_name)
            ], limit=1)

            if not field:
                _logger.warning(f"Campo {field_name} no encontrado")
                return False

            # Elimina de vistas
            self._remove_field_from_all_views(field_name)

            # Elimina posibles restricciones
            self._cr.execute(f"""
                ALTER TABLE {self._table} 
                DROP CONSTRAINT IF EXISTS {self._table}_{field_name}_check
            """)

            # Elimina la columna
            self._cr.execute(f"""
                ALTER TABLE {self._table} 
                DROP COLUMN IF EXISTS {field_name}
            """)

            # Elimina la definición
            field.unlink()

            return True

        except Exception as e:
            _logger.error(f"Error seguro eliminando campo: {str(e)}")
            return False

    def action_delete_dynamic_field(self):
        self.ensure_one()
        field_id = self.env.context.get('active_field_id')

        if not field_id:
            raise UserError(_("Error: No se proporcionó ID de campo a eliminar"))

        try:
            # 1. Verificar existencia del campo
            field = self.env['ir.model.fields'].search([
                ('id', '=', field_id),
                ('model', '=', self._name)
            ])

            if not field:
                raise UserError(_("El campo no existe o ya fue eliminado"))

            field_name = field.name

            # 2. Eliminar de vistas (método mejorado)
            self._remove_field_from_all_views_safe(field_name)

            # 3. Eliminar columna de la base de datos (con verificación)
            self._cr.execute(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = %s 
                AND column_name = %s
            """, [self._table, field_name])

            if self._cr.fetchone():
                self._cr.execute(f"ALTER TABLE {self._table} DROP COLUMN {field_name}")

            # 4. Eliminar definición
            field.unlink()

            # 5. Limpiar caché
            self.env['ir.ui.view'].clear_caches()

            return {'type': 'ir.actions.client', 'tag': 'reload'}

        except Exception as e:
            _logger.error("Error eliminando campo %s: %s", field_name, str(e))
            raise UserError(_("Error completo al eliminar campo: %s") % str(e))

    def _remove_field_from_all_views_safe(self, field_name):
        """Elimina el campo de vistas sin errores de índice"""
        try:
            views = self.env['ir.ui.view'].search([
                ('model', '=', self._name),
                ('arch_db', 'ilike', field_name)
            ])

            for view in views:
                try:
                    arch = etree.fromstring(view.arch_db)
                    nodes = arch.xpath(f"//field[@name='{field_name}']")

                    if not nodes:  # Evita "index out of range"
                        continue

                    for node in nodes:
                        parent = node.getparent()
                        if parent is not None:
                            parent.remove(node)

                    view.arch_db = etree.tostring(arch)

                except Exception as e:
                    _logger.warning("Error procesando vista %s: %s", view.id, str(e))
                    continue

        except Exception as e:
            _logger.error("Error general limpiando vistas: %s", str(e))
            raise

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
                'created_at': fields.Datetime.now().isoformat(),
                'created_by': self.env.user.id,
            }
            
            if self.dynamic_field_type == 'selection' and self.selection_options:
                field_data['options'] = self.selection_options.split('\n')
            
            existing_data = json.loads(self.dynamic_fields_data) if self.dynamic_fields_data else {}
            existing_data[field_name] = field_data
            self.dynamic_fields_data = json.dumps(existing_data, indent=2)
            
        except Exception as e:
            _logger.error("Metadata storage failed: %s", str(e))
            raise UserError(_("Failed to store field metadata: %s") % str(e))

    def _clean_field_metadata(self, field_name):
        """Remove field metadata from storage"""
        if self.dynamic_fields_data:
            try:
                data = json.loads(self.dynamic_fields_data)
                if field_name in data:
                    del data[field_name]
                    self.dynamic_fields_data = json.dumps(data, indent=2)
            except Exception as e:
                _logger.error("Metadata cleanup failed: %s", str(e))

    def _remove_column_from_table(self, field_name):
        """Remove physical column from database"""
        self._cr.execute(f"ALTER TABLE {self._table} DROP COLUMN IF EXISTS {field_name}")

    def _remove_field_from_views(self, field_name):
        """Remove field references from views"""
        View = self.env['ir.ui.view']
        views = View.search([('model', '=', self._name)])

        for view in views:
            try:
                if field_name in view.arch_db:
                    arch = etree.fromstring(view.arch_db)
                    for node in arch.xpath(f"//field[@name='{field_name}']"):
                        node.getparent().remove(node)
                    view.write({'arch_db': etree.tostring(arch)})
            except Exception as e:
                _logger.warning("View %s update failed: %s", view.id, str(e))
    
    def action_create_dynamic_field_from_wizard(self):
        """Wrapper method to maintain compatibility"""
        return self.action_create_dynamic_field()
    
    def _get_dynamic_fields_selection(self):
        """Get list of available dynamic fields"""
        Field = self.env['ir.model.fields'].sudo()
        return [(f.name, f.field_description or f.name) 
                for f in Field.search([
                    ('model', '=', self._name),
                    ('state', '=', 'manual'),
                    ('name', 'like', 'x_%')
                ])]

   

 

   

 
