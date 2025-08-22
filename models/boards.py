from odoo import models, api, fields
from odoo.exceptions import UserError

STATES = [
    ('new', 'New'),
    ('in_progress', 'In Progress'),
    ('done', 'Done'),
    ('stuck', 'Stuck')
]
class Boards(models.Model):
    _name = 'boards.planner'
    _description = 'Model designed to create or modify tasks assigned to employees'
    
    name = fields.Char(string="Tablero")
    department_id = fields.Many2one('hr.department', string='Departamento')
    responsible_person_id = fields.Many2one('hr.employee', string='Responsable', compute='_compute_responsible_person', store=True)
    pick_from_dept = fields.Boolean('Solo miembros del departamento')
    member_ids = fields.Many2many('hr.employee', string='Miembros')
    task_ids = fields.One2many('task.board', 'department_id', invisible=True, string='Grupos')

    @api.depends('department_id', 'department_id.manager_id')
    def _compute_responsible_person(self):
        for record in self:
            if record.department_id and record.department_id.manager_id:
                record.responsible_person_id = record.department_id.manager_id
            else:
                record.responsible_person_id = False

    def delete_cards(self):
        employee = self.env.user.employee_id
        if not employee:
            raise UserError("No se pudo identificar al empleado actual.")
        
        management_dept = self.env['hr.department'].search([('name', '=', 'Management')], limit=1)
        
        # Verificar si el empleado es del departamento Management
        is_management = employee.department_id and management_dept and employee.department_id.id == management_dept.id
        
        if employee not in self.member_ids and not is_management:
            raise UserError("No tienes permisos para eliminar este registro.")
        
        self.unlink()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
    
    def open_task_kanban(self):
        """
        Abre la vista Kanban para ver únicamente las tareas del tablero actual.
        """
        self.ensure_one()
    
        employee = self.env.user.employee_id
        if not employee:
            raise UserError("No se pudo identificar al empleado actual.")
        
        management_dept = self.env['hr.department'].search([('name', '=', 'Management')], limit=1)
        
        # Verificar si el empleado es del departamento Management
        is_management = employee.department_id and management_dept and employee.department_id.id == management_dept.id
        
        # Verificar acceso: debe ser miembro O ser del departamento Management
        has_access = employee in self.member_ids or is_management
        
        if not has_access:
            raise UserError("No tienes acceso a este tablero.")
    
        return {
            'type': 'ir.actions.act_window',
            'name': f'Tablero: {self.name}',
            'res_model': 'task.board',
            'view_mode': 'kanban',
            'view_id': self.env.ref('task_planner.activity_planner_task_view_kanban').id,
            'target': 'current',
            'domain': [('department_id', '=', self.id)],
            'context': {
                'default_name': 'Nueva Tarea',
                'default_department_id': self.id,
            },
        }

    def open_board_form(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Editar Tablero',
            'res_model': 'boards.planner',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.onchange('pick_from_dept')
    def get_employees(self):
        if self.pick_from_dept and self.department_id:
            return {'domain': {'member_ids': [('department_id', '=', self.department_id.id)]}}
        else:
            return {'domain': {'member_ids': []}}

    @api.model
    def _get_accessible_boards(self):
        employee = self.env.user.employee_id
        if not employee or not employee.department_id:
            return self.env['boards.planner']
        
        management_dept = self.env['hr.department'].search([('name', '=', 'Management')], limit=1)
        
        # Verificar si el empleado es del departamento Management
        is_management = management_dept and employee.department_id.id == management_dept.id
        
        if is_management:
            return self.search([]) 
        
        # Para empleados no-management, retornar tableros de su departamento
        return self.search([('department_id', '=', employee.department_id.id)])

    # Método para evitar errores al acceder department_id eliminado
    def check_department_access(self):
        """Verifica que el departamento aún exista"""
        for record in self:
            if record.department_id and not record.department_id.exists():
                record.department_id = False
                record.responsible_person_id = False

    # Sobrescribir read para manejar departamentos eliminados
    def read(self, fields=None, load='_classic_read'):
        self.check_department_access()
        return super(Boards, self).read(fields=fields, load=load)