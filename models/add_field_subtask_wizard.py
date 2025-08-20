from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import re
import logging

_logger = logging.getLogger(__name__)

class AddFieldSubtaskWizard(models.TransientModel):
    _name = 'add.field.subtask.wizard'
    _description = 'Asistente para crear campos dinámicos en actividades'

    # Campos del wizard
    field_name = fields.Char(string="Nombre Técnico", required=True, 
                           help="Puede usar cualquier nombre. Ej: mi_campo_123, campo2024, etc.")
    field_label = fields.Char(string="Etiqueta Visible", required=True)
    field_type = fields.Selection([
        ('char', 'Texto'),
        ('integer', 'Entero'),
        ('float', 'Decimal'),
        ('date', 'Fecha'),
        ('datetime', 'Fecha/Hora'),
        ('boolean', 'Booleano'),
        ('selection', 'Selección')],
        string="Tipo de Campo",
        required=True,
        default='char'
    )
    selection_options = fields.Text(
        string="Opciones de Selección",
        help="Formato: clave:valor\nuno: Opción 1\ndos: Opción 2"
    )
    default_value = fields.Text(string="Valor por Defecto")
    
    # Campo que apunta a subtask.board (como solicitas)
    subtask_id = fields.Many2one(
    'subtask.board',
    string="Subtarea Relacionada",
    required=True,
    default=lambda self: self._default_subtask_id(),
    ondelete='cascade'  # ← AÑADE ESTA LÍNEA
    )

    # Campo computado para mostrar el nombre de la subtarea
    subtask_name = fields.Char(
        string="Nombre de Subtarea",
        compute='_compute_subtask_name',
        readonly=True
    )

    @api.model
    def _default_subtask_id(self):
        """Obtiene la subtarea del contexto"""
        return self.env.context.get('active_id')

    @api.depends('subtask_id')
    def _compute_subtask_name(self):
        """Calcula el nombre de la subtarea"""
        for record in self:
            record.subtask_name = record.subtask_id.name if record.subtask_id else False

    def action_create_dynamic_field(self):
        """Crea el campo dinámico en las actividades de la subtarea"""
        self.ensure_one()

        _logger.info("✅ Wizard ejecutado para subtask.board ID: %s", self.subtask_id.id)
        _logger.info("✅ Nombre de Subtarea: %s", self.subtask_id.name)

        # Validaciones adicionales
        if self.field_type == 'selection' and not self.selection_options:
            raise UserError(_("¡Error! Debe ingresar opciones para campos de selección"))

        # Generar nombre técnico con prefijo
        field_name = self._generate_field_name()

        _logger.info("Campo a crear: %s en subtask.activity", field_name)

        # Verificar si el campo ya existe ANTES de intentar crearlo
        if self._field_already_exists(field_name):
            raise UserError(_("❌ El campo '%s' ya existe en las actividades. Por favor, use un nombre diferente.") % field_name)

        try:
            # 1. Crear columna en la base de datos
            self._create_column_in_db(field_name)

            # 2. Registrar el campo en ir.model.fields
            self._register_field_in_ir(field_name)

            # 3. Actualizar vistas
            self._update_views(field_name)

            # 4. Limpiar cachés de forma segura
            self._safe_cache_clear()

            _logger.info("✅ Campo %s creado exitosamente para actividades de la subtarea %s", 
                        field_name, self.subtask_id.name)

            # 5. Recargar la página automáticamente
            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }

        except Exception as e:
            _logger.error("❌ Error creando campo: %s", str(e))
            # Revertir cambios si hay error
            try:
                # Solo revertir si el campo no existía previamente
                if not self._field_already_exists_in_db(field_name):
                    self.env.cr.execute(f"ALTER TABLE subtask_activity DROP COLUMN IF EXISTS {field_name}")
                # Eliminar registro en ir.model.fields si se creó
                field_record = self.env['ir.model.fields'].search([
                    ('model', '=', 'subtask.activity'),
                    ('name', '=', field_name),
                    ('state', '=', 'manual')
                ], limit=1)
                if field_record:
                    field_record.unlink()
            except Exception as revert_error:
                _logger.warning("⚠️ Error al revertir cambios: %s", str(revert_error))
            
            raise UserError(_("Error al crear campo: %s") % str(e))

    def _field_already_exists(self, field_name):
        """Verifica si el campo ya existe en la base de datos o en ir.model.fields"""
        # Verificar en la base de datos
        if self._field_already_exists_in_db(field_name):
            return True
        
        # Verificar en ir.model.fields
        field_record = self.env['ir.model.fields'].search([
            ('model', '=', 'subtask.activity'),
            ('name', '=', field_name)
        ], limit=1)
        
        return bool(field_record)

    def _field_already_exists_in_db(self, field_name):
        """Verifica si la columna ya existe en la tabla de la base de datos"""
        try:
            self.env.cr.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'subtask_activity' 
                AND column_name = %s
            """, (field_name,))
            return bool(self.env.cr.fetchone())
        except Exception as e:
            _logger.warning("⚠️ Error al verificar columna en BD: %s", str(e))
            return False

    def _generate_field_name(self):
        """Genera nombre técnico válido con prefijo x_ - SIN RESTRICCIONES"""
        # Convertir a minúsculas y reemplazar espacios con guiones bajos
        clean_name = self.field_name.strip().lower().replace(' ', '_')
        
        # Reemplazar caracteres especiales con guiones bajos
        clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', clean_name)
        
        # Asegurar que no comience con número (para compatibilidad con BD)
        if clean_name and clean_name[0].isdigit():
            clean_name = 'x_' + clean_name
        # Agregar prefijo x_ si no lo tiene
        elif not clean_name.startswith('x_'):
            clean_name = 'x_' + clean_name
            
        return clean_name

    def _create_column_in_db(self, field_name):
        """Crea la columna física en la base de datos de subtask.activity"""
        column_type = {
            'char': 'VARCHAR(255)',
            'integer': 'INTEGER',
            'float': 'NUMERIC',
            'boolean': 'BOOLEAN',
            'date': 'DATE',
            'datetime': 'TIMESTAMP',
            'selection': 'VARCHAR(255)'
        }.get(self.field_type)
        
        if not column_type:
            raise UserError(_("Tipo de campo no válido: %s") % self.field_type)
        
        try:
            # Verificar nuevamente antes de crear (doble verificación)
            if self._field_already_exists_in_db(field_name):
                raise UserError(_("El campo '%s' ya existe en la base de datos.") % field_name)
            
            query = f"""
                ALTER TABLE subtask_activity 
                ADD COLUMN {field_name} {column_type}
            """
            self.env.cr.execute(query)
            _logger.info("✅ Columna %s creada en tabla subtask_activity", field_name)
            
        except Exception as e:
            _logger.error("❌ Error creando columna: %s", str(e))
            if "already exists" in str(e):
                raise UserError(_("El campo '%s' ya existe en la base de datos. Por favor, use un nombre diferente.") % field_name)
            else:
                raise UserError(_("Error técnico al crear el campo. Consulte los logs."))
    
    def _safe_cache_clear(self):
        """Limpieza segura de cachés sin recargar modelos"""
        try:
            # Limpiar cachés del registry
            registry = self.env.registry
            if hasattr(registry, 'clear_cache'):
                registry.clear_cache()
            
            # Limpiar cachés del environment
            if hasattr(self.env, 'clear_caches'):
                self.env.clear_caches()
            elif hasattr(self.env, 'invalidate_all'):
                self.env.invalidate_all()
                
            # Limpiar cachés específicos de campos
            if hasattr(self.env.registry, '_field_defs'):
                if 'subtask.activity' in self.env.registry._field_defs:
                    del self.env.registry._field_defs['subtask.activity']
                    
            _logger.info("✅ Cachés limpiados de forma segura")
            
        except Exception as e:
            _logger.info("ℹ️  Info de caché: %s", str(e))

    def get_dynamic_fields_for_subtask(self, subtask_id):
        """Obtiene los campos dinámicos específicos para una subtarea"""
        all_dynamic_fields = self.env['ir.model.fields'].search([
            ('model', '=', 'subtask.activity'),
            ('name', 'like', 'x_%'),
            ('state', '=', 'manual')
        ])

        # Filtrar campos que pertenecen a esta subtarea específica
        subtask_fields = []
        for field in all_dynamic_fields:
            if str(subtask_id) in field.help or f"ID: {subtask_id}" in field.help:
                subtask_fields.append(field)

        return subtask_fields

    def _register_field_in_ir(self, field_name):
        """Crea el registro en ir.model.fields para subtask.activity con info de subtarea"""
        model_id = self.env['ir.model'].search([('model', '=', 'subtask.activity')], limit=1)
        if not model_id:
            raise UserError(_("Modelo subtask.activity no encontrado"))

        # Verificar si el campo ya existe en ir.model.fields
        existing_field = self.env['ir.model.fields'].search([
            ('model', '=', 'subtask.activity'),
            ('name', '=', field_name)
        ], limit=1)
        
        if existing_field:
            raise UserError(_("El campo '%s' ya está registrado en el sistema.") % field_name)

        field_vals = {
            'name': field_name,
            'model_id': model_id.id,
            'field_description': self.field_label or self.field_name,
            'ttype': self.field_type,
            'state': 'manual',
            'store': True,
            'help': f"Campo dinámico para subtarea: {self.subtask_id.name} (ID: {self.subtask_id.id})",
        }

        # Manejar campos de selección
        if self.field_type == 'selection' and self.selection_options:
            options = []
            for line in self.selection_options.split('\n'):
                line = line.strip()
                if line and ':' in line:
                    key, val = line.split(':', 1)
                    options.append((key.strip(), val.strip()))
            if options:
                field_vals['selection'] = str(options)

        try:
            self.env['ir.model.fields'].create(field_vals)
            _logger.info("✅ Campo %s registrado en ir.model.fields para subtask.activity de la subtarea %s", 
                        field_name, self.subtask_id.name)

        except Exception as e:
            _logger.error("❌ Error registrando campo: %s", str(e))
            # Revertir la columna de la BD si falla el registro
            try:
                if not self._field_already_exists_in_db(field_name):
                    self.env.cr.execute(f"ALTER TABLE subtask_activity DROP COLUMN IF EXISTS {field_name}")
            except:
                pass
            raise UserError(_("Error al registrar el campo. Consulte los logs."))

    def _update_views(self, field_name):
        """Actualiza las vistas de subtask.activity para incluir el nuevo campo con condición de subtarea"""
        try:
            field_label = self.field_label or self.field_name

            # Vista Tree - Buscar la vista tree de subtask.activity
            tree_view = self.env.ref('task_planner.view_subtask_activity_tree', raise_if_not_found=False)

            if tree_view:
                arch_tree = f"""
                <data>
                    <xpath expr="//field[@name='person']" position="after">
                        <field name="{field_name}" string="{field_label}" 
                               invisible="context.get('default_subtask_id') != {self.subtask_id.id}"/>
                    </xpath>
                </data>
                """

                self.env['ir.ui.view'].create({
                    'name': f'subtask.activity.tree.dynamic.{field_name}.{self.subtask_id.id}',
                    'model': 'subtask.activity',
                    'inherit_id': tree_view.id,
                    'arch': arch_tree,
                    'type': 'tree',
                    'priority': 100,
                })
                _logger.info("✅ Vista tree actualizada con campo %s para subtarea %s", field_name, self.subtask_id.id)

            # Vista Form - Buscar la vista form de subtask.activity
            form_view = self.env.ref('task_planner.view_subtask_activity_form', raise_if_not_found=False)

            if form_view:
                arch_form = f"""
                <data>
                    <xpath expr="//field[@name='person']" position="after">
                        <field name="subtask_id" invisible="1"/>
                        <field name="{field_name}" string="{field_label}" 
                               attrs="{{'invisible': [('subtask_id', '!=', {self.subtask_id.id})]}}"/>
                    </xpath>
                </data>
                """

                self.env['ir.ui.view'].create({
                    'name': f'subtask.activity.form.dynamic.{field_name}.{self.subtask_id.id}',
                    'model': 'subtask.activity',
                    'inherit_id': form_view.id,
                    'arch': arch_form,
                    'type': 'form',
                    'priority': 100,
                })
                _logger.info("✅ Vista form actualizada con campo %s para subtarea %s", field_name, self.subtask_id.id)

        except Exception as e:
            _logger.error("❌ Error actualizando vistas: %s", str(e))
            raise UserError(_("Error al actualizar vistas. Consulte los logs."))

    def _reload_model(self):
        """Fuerza la recarga del modelo subtask.activity de forma segura"""
        try:
            _logger.info("🔁 Iniciando recarga segura del modelo")

            try:
                if hasattr(self.env.registry, 'clear_cache'):
                    self.env.registry.clear_cache()
                    _logger.info("✅ Cache del registry limpiado")
            except Exception as e:
                _logger.warning("⚠️  Error limpiando cache del registry: %s", str(e))

            try:
                self.env.registry._clear_cache()
                _logger.info("✅ Cache interno del registry limpiado")
            except:
                pass

            try:
                self.env.invalidate_all()
                _logger.info("✅ Environment invalidado")
            except:
                pass
            
            try:
                if hasattr(self.pool, '_field_defs'):
                    if 'subtask.activity' in self.pool._field_defs:
                        del self.pool._field_defs['subtask.activity']
                        _logger.info("✅ Definiciones de campos limpiadas")
            except:
                pass

            _logger.info("✅ Recarga segura completada")

        except Exception as e:
            _logger.warning("⚠️  Advertencia en recarga segura: %s", str(e))
    

    

    