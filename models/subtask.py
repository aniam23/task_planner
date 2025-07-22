from odoo import models, api, fields
from odoo.exceptions import ValidationError
from .boards import STATES

class SubtaskBoard(models.Model):
    _name = 'subtask.board'
    _description = 'Subtarea del Planificador de Actividades'
    _inherit = ['mail.thread']
    
    sequence = fields.Integer(string='Sequence', default=10)
    completion_date = fields.Datetime(string="Timeline")
    drag = fields.Integer()
    files = fields.Many2many(comodel_name="ir.attachment", string="Files")
    name = fields.Char('Subtask Name', required=True)
    task_id = fields.Many2one('task.board', string='Task', required=True)
    state = fields.Selection(STATES, default="new", string="State")
    person = fields.Many2one(
        'hr.employee', 
        string='Assigned To', 
        tracking=True,
        domain="[('id', 'in', allowed_member_ids)]"
    )
    activity_line_ids = fields.One2many('subtask.activity', 'subtask_id', string='Actividades')
    # Campo computado para el dominio
    allowed_member_ids = fields.Many2many(
        'hr.employee',
        string='Allowed Members',
        compute='_compute_allowed_member_ids',
        help="Members of the parent task's department"
    )
    
    def action_open_activity_tree(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'subtask.activity',
            'view_mode': 'tree',
            'target': 'new',
            'context': {
                'default_res_model': 'subtask.board',
                'default_res_id': self.id,
            }
        }

    @api.depends('task_id.department_id.member_ids')
    def _compute_allowed_member_ids(self):
        for subtask in self:
            if subtask.task_id and subtask.task_id.department_id:
                subtask.allowed_member_ids = subtask.task_id.department_id.member_ids
            else:
                subtask.allowed_member_ids = False

    @api.constrains('person', 'task_id')
    def _check_person_selection(self):
        for subtask in self:
            # Verifica si el task_id existe y tiene department_id
            if subtask.task_id and subtask.task_id.department_id:
                # Verifica si pick_from_dept existe y es True, o si no existe el campo
                pick_from_dept = getattr(subtask.task_id, 'pick_from_dept', True)
                if pick_from_dept:  # Si es True o el campo no existe
                    if subtask.person and subtask.person.id not in subtask.task_id.department_id.member_ids.ids:
                        raise ValidationError(
                        "El empleado asignado debe ser miembro del departamento de la tarea principal"
                    )

    