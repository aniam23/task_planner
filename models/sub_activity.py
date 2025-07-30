from odoo import models, fields

class SubtaskActivity(models.Model):
    _name = 'subtask.activity'
    _description = 'Actividad Interna de Subtarea'

    name = fields.Char(string='Subtarea', required=True)
    date_deadline = fields.Date(string='Fecha')
    done = fields.Boolean(string='Completado')
    subtask_id = fields.Many2one('subtask.board', string='Subtarea', ondelete='cascade', required=True)
    person = fields.Many2one(
    'hr.employee',
    string='Responsable',
    domain="[('id', 'in',allowed_member_ids)]"
    )
