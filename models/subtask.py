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
    files = fields.Many2many(comodel_name="ir.attachment", string="Archivos")
    name = fields.Char(string='Nombre de la tarea', required=True)
    task_id = fields.Many2one('task.board', string='Tarea', required=True)
    state = fields.Selection(STATES, default="new", string="Estado")
    
    # Cambiamos a related field en lugar de computed para disponibilidad inmediata
    allowed_member_ids = fields.Many2many(
        'hr.employee',
        string='Miembros permitidos',
        # related='task_id.allowed_member_ids',
        readonly=True,
        compute='compute_allowed_member_ids'
    )
    
    person = fields.Many2one(
        'hr.employee', 
        string='Responsable', 
        tracking=True,
        domain="[('id', 'in', allowed_member_ids)]"
    )
    
    activity_line_ids = fields.One2many('subtask.activity', 'subtask_id', string='Subtareas')
    
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

    @api.constrains('person', 'task_id')
    def _check_person_selection(self):
        for subtask in self:
            if subtask.task_id and subtask.task_id.department_id:
                pick_from_dept = getattr(subtask.task_id, 'pick_from_dept', True)
                if pick_from_dept:
                    if subtask.person and subtask.person.id not in subtask.task_id.department_id.member_ids.ids:
                        raise ValidationError(
                            "El empleado asignado debe ser miembro del departamento de la tarea principal"
                        )
    @api.depends('task_id')
    def compute_allowed_member_ids(self):
        self.allowed_member_ids = self.task_id.allowed_member_ids

   

 
