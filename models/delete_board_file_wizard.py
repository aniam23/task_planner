from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
import re

_logger = logging.getLogger(__name__)

class DeleteBoardFileWizard(models.TransientModel):
    _name = 'delete.board.file.wizard'
    _description = 'Asistente para eliminar campos dinámicos'

    task_id_field = fields.Many2one(
        'task.board', 
        string='Tarea',
        default=lambda self: self.env.context.get('default_task_id_field')
    )
    
    field_to_delete = fields.Many2one(
        'ir.model.fields',
        string="Campo a eliminar",
        required=True,
        domain="[('model', '=', 'task.board'), ('state', '=', 'manual'), ('name', 'like', 'x_%')]"
    )

    def action_delete_dynamic_field(self):
        self.ensure_one()
        if not self.field_to_delete:
            raise UserError(_("No se ha seleccionado ningún campo para eliminar."))

        field_name = self.field_to_delete.name

        try:
            # 1. PRIMERO eliminar TODAS las referencias en vistas
            self._delete_all_field_references(field_name)

            # 2. Eliminar el registro de ir.model.fields
            field_id = self.field_to_delete.id
            self.field_to_delete.unlink()
            _logger.info("✅ Registro %s eliminado de ir.model.fields", field_id)

            # 3. Eliminar la columna de la base de datos
            self.env.cr.execute(f"ALTER TABLE subtask_activity DROP COLUMN IF EXISTS {field_name}")
            _logger.info("✅ Columna %s eliminada de la base de datos", field_name)

            # 4. Limpiar cachés de forma completa
            self._complete_cache_clear()

            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }

        except Exception as e:
            _logger.error("❌ Error eliminando campo %s: %s", field_name, str(e))
            raise UserError(_("Error al eliminar campo '%s': %s") % (field_name, str(e)))
    def _delete_all_field_references(self, field_name):
        """Elimina TODAS las referencias a campos en vistas"""
        try:
            # Buscar en TODOS los modelos, no solo en subtask.activity
            all_views = self.env['ir.ui.view'].search([])
            views_to_clean = self.env['ir.ui.view']
            
            for view in all_views:
                try:
                    arch = view.arch_db or ''
                    if field_name in arch:
                        views_to_clean |= view
                        _logger.info("✅ Vista %s contiene el campo %s - Marcada para limpiar", view.name, field_name)
                except Exception as e:
                    _logger.warning("⚠️ Error revisando vista %s: %s", view.name, str(e))
                    continue
            
            # Limpiar referencias en las vistas encontradas
            for view in views_to_clean:
                self._clean_field_from_view(view, field_name)
                
        except Exception as e:
            _logger.error("❌ Error crítico al limpiar referencias: %s", str(e))
            raise UserError(_("Error al limpiar referencias del campo. Consulte los logs."))

    def _clean_field_from_view(self, view, field_name):
        """Elimina referencias a un campo específico de una vista"""
        try:
            arch = view.arch_db or ''
            
            # Patrones para buscar referencias al campo
            patterns = [
                f'name="{field_name}"',
                f'name=\'{field_name}\'',
                f'"{field_name}"',
                f"'{field_name}'"
            ]
            
            cleaned_arch = arch
            for pattern in patterns:
                # Eliminar campos completos que referencien al campo
                cleaned_arch = re.sub(
                    rf'<field[^>]*{pattern}[^>]*/>', 
                    '', 
                    cleaned_arch
                )
                
                # Eliminar atributos que contengan referencias al campo
                cleaned_arch = re.sub(
                    rf'(\s+[a-zA-Z_]+=["\'][^"\']*{pattern}[^"\']*["\'])', 
                    '', 
                    cleaned_arch
                )
            
            # Actualizar la vista solo si hubo cambios
            if cleaned_arch != arch:
                view.write({'arch_db': cleaned_arch})
                _logger.info("✅ Vista %s limpiada de referencias a %s", view.name, field_name)
                
        except Exception as e:
            _logger.error("❌ Error limpiando vista %s: %s", view.name, str(e))

    def _complete_cache_clear(self):
        """Limpieza completa de todos los cachés"""
        try:
            self.env.registry.clear_cache()
            self.env.invalidate_all()
            _logger.info("✅ Cachés limpiados completamente")
        except Exception as e:
            _logger.warning("⚠️ Advertencia al limpiar cachés: %s", str(e))

    @api.model
    def default_get(self, fields_list):
        """Establece valores por defecto"""
        result = super().default_get(fields_list)
        context = self.env.context
        
        if 'active_id' in context and context.get('active_model') == 'subtask.activity':
            result['activity_id'] = context['active_id']
        
        return result
    # def action_open_delete_board_file_wizard(self):
    #     if not self.field_to_delete:
    #         raise UserError(_("No se ha seleccionado ningún campo para eliminar."))

    #     field_name = self.field_to_delete.name
    #     field_id = self.field_to_delete.id

    #     try:
    #         # 1. Primero eliminar todas las vistas que usan este campo
    #         self._delete_field_views(field_name)

    #         # 2. Eliminar la columna de la base de datos
    #         self.env.cr.execute(f"ALTER TABLE TASK DROP COLUMN IF EXISTS {field_name}")
    #         _logger.info("✅ Columna %s eliminada de la base de datos", field_name)

    #         # 3. Eliminar el registro de ir.model.fields
    #         self.field_to_delete.unlink()
    #         _logger.info("✅ Registro %s eliminado de ir.model.fields", field_id)

    #         # 4. Limpiar cachés de forma segura
    #         self._safe_cache_clear()

    #         return {
    #             'type': 'ir.actions.client',
    #             'tag': 'reload',
    #         }

    #     except Exception as e:
    #         _logger.error("❌ Error eliminando campo %s: %s", field_name, str(e))
    #         raise UserError(_("Error al eliminar campo '%s': %s") % (field_name, str(e)))

    # def _safe_cache_clear(self):
    #     """Limpieza segura de cachés sin recargar modelos"""
    #     try:
    #         # Métodos alternativos para limpiar cachés
    #         if hasattr(self.env.registry, 'clear_caches'):
    #             self.env.registry.clear_caches()
    #             _logger.info("✅ Cache del registry limpiado con clear_caches()")
    #         elif hasattr(self.env, 'clear_caches'):
    #             self.env.clear_caches()
    #             _logger.info("✅ Cache del environment limpiado")
    #         elif hasattr(self.env, 'invalidate_all'):
    #             self.env.invalidate_all()
    #             _logger.info("✅ Environment invalidado")

    #         # Limpiar cachés específicos de campos
    #         if hasattr(self.env.registry, '_field_defs'):
    #             if 'task.board' in self.env.registry._field_defs:
    #                 del self.env.registry._field_defs['task.board']
    #                 _logger.info("✅ Definiciones de campos limpiadas")

    #     except Exception as e:
    #         _logger.warning("⚠️ Advertencia al limpiar cachés: %s", str(e))

    # def _delete_field_views(self, field_name):
    #     """Elimina todas las vistas que hacen referencia al campo dinámico"""
    #     try:
   
    #         specific_view = self.env['ir.ui.view'].search([
    #             ('name', '=', 'activity_planner_task_view_tree'),
    #             ('model', '=', 'task.board')
    #         ], limit=1)
            
    #         views_to_delete = self.env['ir.ui.view']
            
    #         if specific_view and specific_view.arch and field_name in specific_view.arch:
    #             views_to_delete |= specific_view
    #             _logger.info("📋 Vista  encontrada con campo %s", field_name)
            
    #         # Buscar todas las demás vistas que contengan el campo
    #         all_views = self.env['ir.ui.view'].search([
    #             ('model', '=', 'task.board'),
    #             ('id', '!=', specific_view.id if specific_view else False)
    #         ])
            
    #         for view in all_views:
    #             if view.arch and field_name in view.arch:
    #                 views_to_delete |= view
    #                 _logger.info("📋 Vista %s encontrada con campo %s", view.name, field_name)
            
    #         # También buscar vistas por nombre que coincidan con patrones dinámicos
    #         pattern_views = self.env['ir.ui.view'].search([
    #             ('name', 'ilike', f'%{field_name}%'),
    #             ('model', '=', 'task.board')
    #         ])
    #         views_to_delete |= pattern_views
            
    #         # Eliminar duplicados y verificar que existan
    #         views_to_delete = views_to_delete.filtered(lambda v: v.exists())
            
    #         view_count = len(views_to_delete)
            
    #         if views_to_delete:
    #             view_names = views_to_delete.mapped('name')
    #             # Crear backup del XML antes de eliminar (opcional para debugging)
    #             for view in views_to_delete:
    #                 _logger.debug("🔧 Eliminando vista: %s - XML: %s", view.name, view.arch)
                
    #             views_to_delete.unlink()
    #             _logger.info("✅ %d vistas eliminadas para el campo %s: %s", 
    #                         view_count, field_name, view_names)
    #         else:
    #             _logger.info("ℹ️ No se encontraron vistas que usen el campo %s", field_name)
                
    #     except Exception as e:
    #         _logger.error("❌ Error al eliminar vistas del campo %s: %s", field_name, str(e))
    #         raise UserError(_("Error al eliminar vistas del campo '%s': %s") % (field_name, str(e)))