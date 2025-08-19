# -*- coding: utf-8 -*-

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
                           help="Solo letras, números y guiones bajos. Ej: mi_campo")
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
        default=lambda self: self._default_subtask_id()
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

    @api.constrains('field_name')
    def _check_field_name(self):
        """Valida el formato del nombre técnico"""
        for record in self:
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', record.field_name):
                raise ValidationError(_("Nombre inválido. Solo letras, números y guiones bajos."))

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

        try:
            # 1. Crear columna en la base de datos
            self._create_column_in_db(field_name)

            # 2. Registrar el campo en ir.model.fields
            self._register_field_in_ir(field_name)

            # 3. Actualizar vistas
            self._update_views(field_name)

            # 4. Intentar recargar el modelo (pero no fallar si hay error)
            try:
                self._reload_model()
            except Exception as reload_error:
                _logger.warning("⚠️  Advertencia en recarga: %s. El campo se creó pero puede requerir reinicio.", str(reload_error))

            _logger.info("✅ Campo %s creado exitosamente para actividades de la subtarea %s", 
                        field_name, self.subtask_id.name)

            # Mostrar mensaje de éxito
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Campo Creado'),
                    'message': _('El campo %s se creó exitosamente. Puede requerir recargar la página.') % field_name,
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }

        except Exception as e:
            _logger.error("❌ Error creando campo: %s", str(e))
            # Intentar revertir cambios si hay error
            try:
                self.env.cr.execute(f"ALTER TABLE subtask_activity DROP COLUMN IF EXISTS {field_name}")
                self.env['ir.model.fields'].search([
                    ('model', '=', 'subtask.activity'),
                    ('name', '=', field_name)
                ]).unlink()
            except:
                pass
            raise UserError(_("Error al crear campo: %s") % str(e))

    def _generate_field_name(self):
        """Genera nombre técnico válido con prefijo x_"""
        clean_name = re.sub(r'[^a-zA-Z0-9_]', '', self.field_name.strip().lower().replace(' ', '_'))
        return f'x_{clean_name}' if not clean_name.startswith('x_') else clean_name

    def _create_field_directly(self, field_name):
        """Crea el campo directamente en subtask.activity"""
        try:
            # 1. Crear columna en la base de datos
            self._create_column_in_db(field_name)
            
            # 2. Registrar el campo en ir.model.fields
            self._register_field_in_ir(field_name)
            
            # 3. Actualizar vistas
            self._update_views(field_name)
            
            # 4. Forzar recarga del modelo
            self._reload_model()
            
            _logger.info("✅ Campo %s creado exitosamente para actividades de la subtarea %s", 
                        field_name, self.subtask_id.name)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }
            
        except Exception as e:
            _logger.error("❌ Error creando campo: %s", str(e))
            raise UserError(_("Error al crear campo: %s") % str(e))

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
            query = f"""
                ALTER TABLE subtask_activity 
                ADD COLUMN {field_name} {column_type}
            """
            self.env.cr.execute(query)
            _logger.info("✅ Columna %s creada en tabla subtask_activity", field_name)
            
        except Exception as e:
            _logger.error("❌ Error creando columna: %s", str(e))
            raise UserError(_("Error técnico al crear el campo. Consulte los logs."))

    def _register_field_in_ir(self, field_name):
        """Crea el registro en ir.model.fields para subtask.activity"""
        model_id = self.env['ir.model'].search([('model', '=', 'subtask.activity')], limit=1)
        if not model_id:
            raise UserError(_("Modelo subtask.activity no encontrado"))
        
        field_vals = {
            'name': field_name,
            'model_id': model_id.id,
            'field_description': self.field_label or self.field_name,
            'ttype': self.field_type,
            'state': 'manual',
            'store': True,
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
            _logger.info("✅ Campo %s registrado en ir.model.fields para subtask.activity", field_name)
            
        except Exception as e:
            _logger.error("❌ Error registrando campo: %s", str(e))
            # Revertir la columna de la BD si falla el registro
            try:
                self.env.cr.execute(f"ALTER TABLE subtask_activity DROP COLUMN IF EXISTS {field_name}")
            except:
                pass
            raise UserError(_("Error al registrar el campo. Consulte los logs."))

    def _update_views(self, field_name):
        """Actualiza las vistas de subtask.activity para incluir el nuevo campo"""
        try:
            # Vista Tree - Buscar la vista tree de subtask.activity
            tree_view = self.env.ref('task_planner.view_subtask_activity_tree', raise_if_not_found=False)
            
            if tree_view:
                # Crear una vista heredada para el tree view
                arch_tree = f"""
                <data>
                    <xpath expr="//field[@name='person']" position="after">
                        <field name="{field_name}" string="{self.field_label}"/>
                    </xpath>
                </data>
                """
                
                self.env['ir.ui.view'].create({
                    'name': f'subtask.activity.tree.dynamic.{field_name}',
                    'model': 'subtask.activity',
                    'inherit_id': tree_view.id,
                    'arch': arch_tree,
                    'type': 'tree',
                    'priority': 100,
                })
                _logger.info("✅ Vista tree de subtask.activity actualizada con campo %s", field_name)
            
            # Vista Form - Buscar la vista form de subtask.activity
            form_view = self.env.ref('task_planner.view_subtask_activity_form', raise_if_not_found=False)
            
            if form_view:
                # Crear una vista heredada para el form view
                arch_form = f"""
                <data>
                    <xpath expr="//field[@name='person']" position="after">
                        <field name="{field_name}" string="{self.field_label}"/>
                    </xpath>
                </data>
                """
                
                self.env['ir.ui.view'].create({
                    'name': f'subtask.activity.form.dynamic.{field_name}',
                    'model': 'subtask.activity',
                    'inherit_id': form_view.id,
                    'arch': arch_form,
                    'type': 'form',
                    'priority': 100,
                })
                _logger.info("✅ Vista form de subtask.activity actualizada con campo %s", field_name)
            
        except Exception as e:
            _logger.error("❌ Error actualizando vistas: %s", str(e))
            raise UserError(_("Error al actualizar vistas. Consulte los logs."))

    def _reload_model(self):
        """Fuerza la recarga del modelo subtask.activity de forma segura"""
        try:
            _logger.info("🔁 Iniciando recarga segura del modelo")
            
            # Método más seguro: no intentar recargar el modelo completamente
            # En su lugar, limpiar cachés y forzar recarga en la siguiente solicitud
            
            # 1. Limpiar cachés básicos
            try:
                # Limpiar caché del registry si está disponible
                if hasattr(self.env.registry, 'clear_cache'):
                    self.env.registry.clear_cache()
                    _logger.info("✅ Cache del registry limpiado")
            except Exception as e:
                _logger.warning("⚠️  Error limpiando cache del registry: %s", str(e))
            
            # 2. Limpiar cachés específicos
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
            
            # 3. Recargar solo los campos, no el modelo completo
            try:
                # Recargar la definición de campos
                if hasattr(self.pool, '_field_defs'):
                    if 'subtask.activity' in self.pool._field_defs:
                        del self.pool._field_defs['subtask.activity']
                        _logger.info("✅ Definiciones de campos limpiadas")
            except:
                pass
                
            _logger.info("✅ Recarga segura completada - el modelo se cargará en la próxima solicitud")
            
        except Exception as e:
            _logger.warning("⚠️  Advertencia en recarga segura: %s", str(e))
            # No es crítico, el campo ya está creado

    