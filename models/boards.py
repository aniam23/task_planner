from odoo import models, api, fields
from odoo.exceptions import UserError

STATES = [
    ('new', 'New'),
    ('in_progress', 'In Progress'),
    ('done', 'Done'),
    ('stuck', 'Stuck')
]

class Boards(models.Model):
    _name= 'boards.planner'
    _description= 'Model designed to create or modify tasks asigned to employe'
    name = fields.Char(string="Tablero")
    department_id = fields.Many2one('hr.department', string='Departamento')
    responsible_person_id = fields.Many2one('hr.employee', related='department_id.manager_id')
    pick_from_dept = fields.Boolean('Solo miembros del departamento')
    member_ids = fields.Many2many('hr.employee', string='Miembros')
    task_ids = fields.One2many('task.board', 'department_id', invisible=1)

    def delete_cards(self):
        employee = self.env.user.employee_id
        management_dept = self.env['hr.department'].search([('name', '=', 'Management')], limit=1)
        """
        Permitir la eliminacion de tableros si y solo si son de el grupo de administradores
        """
        if not employee or (employee not in self.member_ids and employee.department_id != management_dept):
            raise UserError("Don't have permission to delete this record")
        self.unlink()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
    
    def open_task_kanban(self):
        """
        Abre la vista para ver las tareas creadas en el tablero actual
        """
        self.ensure_one()  # Asegura que solo se está llamando a un tablero
        employee = self.env.user.employee_id
        management_dept = self.env['hr.department'].search([('name', '=', 'Management')], limit=1)
    
        if not employee or (employee not in self.member_ids and employee.department_id != management_dept):
            raise UserError("You do not have acceso a este departamento.")
    
        return {
            'type': 'ir.actions.act_window',
            'name': 'Tasks Board',
            'res_model': 'task.board',
            'view_mode': 'kanban',
            'view_id': self.env.ref('task_planner.activity_planner_task_view_kanban').id,
            'target': 'current',
            'domain': [('id', '=', self.id)],  # 👈 Esta línea filtra solo el tablero actual
            'context': {
                'default_department_id': self.id
            },
        }

    
    def open_board_form(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Edit Board',
            'res_model': 'boards.planner',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.onchange('pick_from_dept')
    def get_employees(self):
        """

        """
        if self.pick_from_dept:
            domain = [('department_id', '=', self.department_id.id)]
        else:
            domain = []
        return {'domain': {'member_ids': domain}}

    @api.model
    def _get_accessible_boards(self):
        employee = self.env.user.employee_id
        management_dept = self.env['hr.department'].search([('name', '=', 'Management')], limit=1)
        if employee and employee.department_id == management_dept:
            return self.search([]) 
        return self.search([('department_id', '=', employee.department_id.id)])