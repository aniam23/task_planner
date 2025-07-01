from odoo import models, api, fields
from odoo.exceptions import ValidationError
from .boards import STATES
import re
import json
class TaskBoard(models.Model):
    _name = 'task.board'
    _description = 'Activity Planner Task'
    _inherit = ['mail.thread']
    completion_date = fields.Datetime(string="Timeline")
    department_id = fields.Many2one(
        'boards.planner', 
        string="Department", 
        ondelete='cascade',
        required=True
    )

    sequence = fields.Integer(string='Sequence', default=10)
    drag = fields.Integer()
    files = fields.Many2many('ir.attachment', string="Files")
    name = fields.Char(string="Task", required=True)
    person = fields.Many2one(
        'hr.employee',
        string='Assigned To',
        tracking=True,
        required=True,
        domain="[('id', 'in', allowed_member_ids)]"
    )

    color = fields.Integer(string='Color Index', compute='_compute_color_from_state', store=True)
    status = fields.Selection(STATES, default="new", string="State")
    subtask_ids = fields.One2many('subtask.board', 'task_id', string='Subtasks')
    allowed_member_ids = fields.Many2many(
        'hr.employee',
        compute='_compute_allowed_members',
        string='Allowed Members'
    )

    color = fields.Integer(string='Color Index', compute='_compute_color_from_state', store=True)
    completed_subtasks = fields.Integer(
        string="Completed Subtasks",
        compute='_compute_progress',
        store=True,
        default=0  # Añadir valor por defecto
    )
    
    total_subtasks = fields.Integer(
        string="Total Subtasks",
        compute='_compute_progress',
        store=True,
        default=0  # Añadir valor por defecto
    )

    progress = fields.Float(
    string="Progress", 
    compute='_compute_progress', 
    store=True,
    group_operator="avg",
    default=0.0
    )

    show_subtasks = fields.Boolean(string="Show Subtasks", default=True)
    parent_id = fields.Many2one('task.board', 'Parent Task', index=True, ondelete='cascade')
    child_ids = fields.One2many('task.board', 'parent_id', 'Sub-tasks')
     # Campos principales existentes (se mantienen igual)
    completion_date = fields.Datetime(string="Timeline")
    department_id = fields.Many2one('boards.planner', string="Department", ondelete='cascade', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    drag = fields.Integer()
    files = fields.Many2many('ir.attachment', string="Files")
    name = fields.Char(string="Task", required=True)
    person = fields.Many2one('hr.employee', string='Assigned To', tracking=True, required=True, domain="[('id', 'in', allowed_member_ids)]")
    status = fields.Selection(STATES, default="new", string="State")
    subtask_ids = fields.One2many('subtask.board', 'task_id', string='Subtasks')
    show_subtasks = fields.Boolean(string="Show Subtasks", default=True)
    parent_id = fields.Many2one('task.board', 'Parent Task', index=True, ondelete='cascade')
    child_ids = fields.One2many('task.board', 'parent_id', 'Sub-tasks')
    # Añade esto junto con los otros campos dinámicos
    selection_options = fields.Text(
    string="Opciones de Selección",
    help="Ingrese opciones en formato clave:valor, una por línea. Ejemplo:\nopcion1:Opción 1\nopcion2:Opción 2"
    )
    DYNAMIC_FIELD_TYPES = [
    ('boolean', 'Booleano'),
    ('integer', 'Entero'),
    ('char', 'Texto'),
    ('float', 'Decimal'),
    ('date', 'Fecha'),
    ('datetime', 'Fecha/Hora'),
    ('selection', 'Selección'),
    ('text', 'Texto Largo')
    ]

    dynamic_field_type = fields.Selection(DYNAMIC_FIELD_TYPES, string='Tipo de Campo')
    dynamic_field_name = fields.Char(string='Nombre del Campo')
    dynamic_field_label = fields.Char(string='Etiqueta del Campo')  # Nuevo campo para la etiqueta
    dynamic_fields_data = fields.Text(string='Datos de Campos Dinámicos', default='{}')
    

    def action_create_dynamic_field(self):
        """Método para crear el campo dinámico"""
        self.ensure_one()

        # Validaciones básicas
        if not self.dynamic_field_type or not self.dynamic_field_name or not self.dynamic_field_label:
            raise ValidationError(_("Debe especificar tipo, nombre y etiqueta del campo"))

        # Formatear nombre del campo
        field_name = self.dynamic_field_name.strip().lower().replace(' ', '_')
        if not field_name.startswith('x_'):
            field_name = f"x_{field_name}"

        # Validar nombre
        if not re.match(r'^[a-z][a-z0-9_]*$', field_name):
            raise ValidationError(_("Nombre inválido. Solo use letras minúsculas, números y guiones bajos"))

        # Obtener modelo actual
        model_id = self.env['ir.model'].search([('model', '=', self._name)])
        if not model_id:
            raise ValidationError(_("No se encontró el modelo asociado"))

        # Verificar si el campo ya existe
        if self.env['ir.model.fields'].search([
            ('model_id', '=', model_id.id),
            ('name', '=', field_name)
        ]):
            raise ValidationError(_("El campo ya existe"))

        # Preparar valores para el campo
        field_vals = {
            'name': field_name,
            'model_id': model_id.id,
            'ttype': self.dynamic_field_type,
            'state': 'manual',
            'field_description': self.dynamic_field_label.strip(),
            'store': True
        }

        # Manejar campos de selección
        if self.dynamic_field_type == 'selection' and self.selection_options:
            options = []
            for line in self.selection_options.split('\n'):
                if line.strip() and ':' in line:
                    key, val = line.split(':', 1)
                    options.append((key.strip(), val.strip()))
            field_vals['selection'] = str(options)

        # Crear el campo
        self.env['ir.model.fields'].create(field_vals)

        # Actualizar campos dinámicos en el registro
        dynamic_fields = json.loads(self.dynamic_fields_data or '{}')
        dynamic_fields[field_name] = {
            'type': self.dynamic_field_type,
            'label': self.dynamic_field_label.strip()
        }
        self.dynamic_fields_data = json.dumps(dynamic_fields)

        # Limpiar campos del formulario
        self.write({
            'dynamic_field_type': False,
            'dynamic_field_name': False,
            'dynamic_field_label': False,
            'selection_options': False
        })

        # Forzar actualización de vistas
        self.env['ir.ui.view'].clear_caches()

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    @api.model
    def get_dynamic_fields(self):
        """Obtener campos dinámicos configurados"""
        try:
            return json.loads(self.dynamic_fields_data or '{}')
        except ValueError:
            return {}

    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        res = super(TaskBoard, self).fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)

        if view_type == 'tree':
            try:
                dynamic_fields = json.loads(self.dynamic_fields_data or '{}')
                if dynamic_fields:
                    doc = etree.XML(res['arch'])
                    tree = doc.xpath("//tree")[0]

                    # Agregar campos dinámicos al tree
                    for field_name, field_data in dynamic_fields.items():
                        if not doc.xpath(f"//field[@name='{field_name}']"):
                            field_attrs = {
                                'name': field_name,
                                'string': field_data.get('label', field_name)
                            }
                            if field_data.get('type') == 'selection':
                                field_attrs['widget'] = 'selection'
                            etree.SubElement(tree, 'field', field_attrs)

                    res['arch'] = etree.tostring(doc, encoding='unicode')
            except Exception as e:
                _logger.warning("Error procesando campos dinámicos: %s", str(e))

        return res

    def action_open_dynamic_field_creator(self):
        """Abrir diálogo para crear campo dinámico"""
        self.ensure_one()
        return {
            'name': ('Agregar Campo Dinámico'),
            'type': 'ir.actions.act_window',
            'res_model': 'task.board',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('task_planner.view_task_board_dynamic_fields_form').id,
            'target': 'new',
        }

    def action_add_subtask (self):
        return {
        'type': 'ir.actions.act_window',
        'name': 'Subtareas',
        'res_model': 'subtask.board',
        'view_mode': 'tree',
        'domain': [('id', 'in', self.subtask_ids.ids)],
        'target': 'new',
    }
    
    @api.depends('subtask_ids', 'subtask_ids.status')
    def _compute_progress(self):
        for task in self:
            completed = task.subtask_ids.filtered(lambda x: x.status == 'done')
            task.completed_subtasks = len(completed)
            task.total_subtasks = len(task.subtask_ids)
            task.progress = (task.completed_subtasks / task.total_subtasks) * 100 if task.total_subtasks > 0 else 0
            
    @api.depends('status')
    def _compute_color_from_state(self):
        for task in self:
            if task.status == 'new':
                task.color = 2  # Amarillo
            elif task.status == 'in_progress':
                task.color = 5  # Naranja
            elif task.status == 'done':
                task.color = 10  # Verde
            elif task.status == 'stuck':
                task.color = 1  # Rojo
            else:
                task.color = 0  # Por defecto

    @api.depends('department_id')
    def _compute_allowed_members(self):
        for task in self:
            task.allowed_member_ids = task.department_id.member_ids

    @api.constrains('person', 'department_id')
    def _check_person_in_department(self):
        for task in self:
            if task.department_id and task.person not in task.department_id.member_ids:
                raise ValidationError(
                    "El empleado asignado no pertenece al departamento seleccionado. "
                    "Miembros válidos: %s" % 
                    ", ".join(task.department_id.member_ids.mapped('name'))
                )

    @api.model
    def create(self, vals):
        task = super().create(vals)
        task._check_person_in_department()
        return task

    def write(self, vals):
        res = super().write(vals)
        self._check_person_in_department()
        return res

    def open_details_form(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Details Board',
            'res_model': 'task.board',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('task_planner.activity_planner_details_view_form').id,
            'target': 'current',
        }