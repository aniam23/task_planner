odoo.define('task_planner.board_colors', function (require) {
    "use strict";
    
    var KanbanRecord = require('web.KanbanRecord');
    
    KanbanRecord.include({
        _render: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                var status = self.record.status.raw_value;
                self.$el.removeClass (function (index, className) {
                    return (className.match (/(^|\s)task-state-\S+/g) || []).join(' ');
                }).addClass('task-state-' + status);
            });
        },
    });
});