from odoo import models, api, fields
from odoo.exceptions import UserError
from .boards import STATES

class TaskBoard(models.Model):
    _name = 'task.board'
    _description = 'Activity Planner Task'
    _inherit = ['mail.thread']

    completion_date = fields.Datetime(string="Timeline")
    department_id = fields.Many2one('boards.planner', 
        string="Department", ondelete='cascade', invisible="1")
    drag = fields.Integer()
    files = fields.Many2many(comodel_name="ir.attachment", 
        string="Files")
    name = fields.Char(string="Task", required=True) 
    pick_from_dept = fields.Boolean(
        string="Restrict to Department Members", 
        default=True,
        help="When enabled, only department members can be assigned")
    status = fields.Selection(STATES, default="new", 
        string="State")
    subtask_ids = fields.One2many('subtask.board', 'task_id', 
        string='Subtasks')

    person = fields.Many2one(
        'hr.employee', 
        string='Assigned To',
        tracking=True,
        required=True,  
    )

    @api.onchange('department_id', 'pick_from_dept')
    def _onchange_department_restriction(self):
        if self.pick_from_dept and self.department_id:
            return {
                'domain': {
                    'person': [('id', 'in', self.department_id.member_ids.ids)]
                }
            }
        return {'domain': {'person': []}}

    @api.model
    def create(self, vals):
        if not vals.get('person'):
            raise UserError("❌ **Error**: ¡Debe asignar un responsable antes de guardar!")
        return super().create(vals)

    def write(self, vals):
        if 'person' in vals and not vals['person']:
            raise UserError("❌ **Error**: ¡No puede dejar la tarea sin responsable!")
        return super().write(vals)
    
   

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