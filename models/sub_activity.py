from odoo import models, fields

class SubtaskActivity(models.Model):
    _name = 'subtask.activity'
    _description = 'Actividad Interna de Subtarea'

    name = fields.Char(string='Descripción de Actividad', required=True)
    date_deadline = fields.Date(string='Fecha Límite')
    done = fields.Boolean(string='Completado')
    subtask_id = fields.Many2one('subtask.board', string='Subtarea', ondelete='cascade', required=True)
    responsible_id = fields.Many2one('hr.employee', string='Responsable')
