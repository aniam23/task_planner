from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
import json

_logger = logging.getLogger(__name__)

class DeleteBoardFileWizard(models.TransientModel):
    _name = 'delete.board.file.wizard'
    _description = 'Wizard para eliminar campos dinámicos'
    
    board_id = fields.Many2one('boards.planner', string="Tablero", required=True)
    field_to_delete = fields.Many2one(
        'ir.model.fields',
        string="Campo a eliminar",
        required=True,
        
    )
    field_name = fields.Char(string="Nombre del campo", compute='_compute_field_name', store=True)

    @api.model
    def default_get(self, fields_list):
        """Establece valores por defecto"""
        result = super().default_get(fields_list)
        context = self.env.context
        
        # Obtener el ID del tablero desde el contexto
        if 'active_id' in context and context.get('active_model') == 'boards.planner':
            result['board_id'] = context['active_id']
        
        return result

    @api.onchange('board_id')
    def _onchange_board_id(self):
        """Actualizar dominio del campo field_to_delete basado en el tablero seleccionado"""
        domain = {}
        if self.board_id:
            # Obtener campos dinámicos específicos de este tablero
            domain = {'field_to_delete': self._get_dynamic_fields_for_board_domain()}
        return {'domain': domain}

    def _get_dynamic_fields_for_board_domain(self):
        """Obtiene el dominio para campos dinámicos específicos del tablero"""
        domain = [('model', '=', 'task.board'), ('state', '=', 'manual')]
        
        if self.board_id:
            # Buscar campos que pertenecen específicamente a este tablero
            task_boards = self.env['task.board'].search([
                ('department_id', '=', self.board_id.id),
                ('dynamic_fields_data', '!=', False)
            ])
            
            field_names = set()
            for task in task_boards:
                try:
                    data = json.loads(task.dynamic_fields_data)
                    for field_name, config in data.items():
                        if (isinstance(config, dict) and 
                            config.get('board_id') == self.board_id.id):
                            field_names.add(field_name)
                except json.JSONDecodeError:
                    continue
            
            if field_names:
                domain.append(('name', 'in', list(field_names)))
            else:
                # Si no hay campos, devolver dominio que no devuelva nada
                domain.append(('id', '=', 0))
        
        return domain

    @api.depends('field_to_delete')
    def _compute_field_name(self):
        """Compute field name from the selected field"""
        for record in self:
            record.field_name = record.field_to_delete.name if record.field_to_delete else False

    def action_delete_dynamic_field(self):
        self.ensure_one()
        if not self.field_to_delete:
            raise UserError(_("No se ha seleccionado ningún campo para eliminar."))

        field_name = self.field_to_delete.name

        try:
            # 1. Eliminar todas las vistas asociadas a este campo y tablero
            self._delete_field_views(field_name)

            # 2. Eliminar metadata de los task boards
            self._remove_field_metadata(field_name)

            # 3. Eliminar el registro de ir.model.fields
            field_id = self.field_to_delete.id
            self.field_to_delete.unlink()
            _logger.info("✅ Registro %s eliminado de ir.model.fields", field_id)

            # 4. Eliminar la columna de la base de datos
            self._safe_remove_column(field_name)

            # 5. Limpiar cachés de forma completa
            self._complete_cache_clear()

            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }

        except Exception as e:
            _logger.error("❌ Error eliminando campo %s: %s", field_name, str(e))
            raise UserError(_("Error al eliminar campo '%s': %s") % (field_name, str(e)))

    def _delete_field_views(self, field_name):
        """Elimina vistas específicas del campo"""
        try:
            board_id = self.board_id.id
            view_pattern = f"task.board.tree.dynamic.{field_name}.board_{board_id}"
            
            views_to_delete = self.env['ir.ui.view'].search([
                ('name', '=', view_pattern),
                ('model', '=', 'task.board')
            ])
            
            if views_to_delete:
                views_to_delete.unlink()
                _logger.info("✅ Vistas eliminadas: %s", view_pattern)
                
        except Exception as e:
            _logger.error("❌ Error eliminando vistas: %s", str(e))

    def _remove_field_metadata(self, field_name):
        """Remove field from stored JSON data for all records in this board"""
        try:
            task_boards = self.env['task.board'].search([
                ('department_id', '=', self.board_id.id),
                ('dynamic_fields_data', '!=', False)
            ])
            
            for task in task_boards:
                if task.dynamic_fields_data:
                    try:
                        data = json.loads(task.dynamic_fields_data)
                        if field_name in data:
                            del data[field_name]
                            task.dynamic_fields_data = json.dumps(data) if data else False
                            _logger.info("✅ Metadata eliminada de task %s", task.id)
                    except json.JSONDecodeError:
                        # Si el JSON está corrupto, limpiar el campo
                        task.dynamic_fields_data = False
        except Exception as e:
            _logger.error("❌ Error removing field metadata: %s", str(e))

    def _safe_remove_column(self, field_name):
        """Safely remove column from database"""
        try:
            self.env.cr.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'task_board' 
                AND column_name = %s
            """, [field_name])

            if self.env.cr.fetchone():
                self.env.cr.execute(
                    f'ALTER TABLE task_board DROP COLUMN IF EXISTS "{field_name}"'
                )
                self.env.cr.commit()
                _logger.info("✅ Columna %s eliminada de la base de datos", field_name)
            else:
                _logger.info("ℹ️ Columna %s no existe en la base de datos", field_name)
                
        except Exception as e:
            self.env.cr.rollback()
            _logger.error("❌ Error eliminando columna: %s", str(e))
            raise

    def _complete_cache_clear(self):
        """Limpieza completa de todos los cachés"""
        try:
            # Limpiar cachés del registro
            self.env.registry.clear_cache()
            
            # Invalidar caché del environment
            self.env.invalidate_all()
            
            # Limpiar caché de vistas
            self.env['ir.ui.view'].clear_caches()
            
            _logger.info("✅ Cachés limpiados completamente")
            
        except Exception as e:
            _logger.warning("⚠️ Advertencia al limpiar cachés: %s", str(e))