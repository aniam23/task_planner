from odoo import models, api, fields
from odoo.exceptions import ValidationError
from .boards import STATES

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

    status = fields.Selection(STATES, default="new", string="State")
    subtask_ids = fields.One2many('subtask.board', 'task_id', string='Subtasks')

    allowed_member_ids = fields.Many2many(
        'hr.employee',
        compute='_compute_allowed_members',
        string='Allowed Members'
    )
    color = fields.Integer(string='Color Index', compute='_compute_color_from_state', store=True)

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