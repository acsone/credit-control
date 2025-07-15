# Copyright 2019 ACSONE SA/NV
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, models


class CreditControlPrinter(models.TransientModel):
    _inherit = "credit.control.printer"

    @api.model
    def _default_line_ids(self):
        lines = super()._default_line_ids()
        if lines is False:
            return False
        lines_and_related = lines.mapped(lambda line: line._get_lower_related_lines())
        return lines_and_related.ids
