# Copyright 2012-2017 Camptocamp SA
# Copyright 2017 Okia SPRL (https://okia.be)
# Copyright 2018 Access Bookings Ltd (https://accessbookings.com)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import api, fields, models


class CreditControlCommunication(models.Model):
    _name = "credit.control.communication"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Credit control communication process"
    _rec_name = 'partner_id'

    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Partner',
        required=True,
        index=True,
    )
    policy_id = fields.Many2one(
        related='policy_level_id.policy_id',
        store=True,
        index=True,
    )
    policy_level_id = fields.Many2one(
        comodel_name='credit.control.policy.level',
        string='Level',
        required=True,
        index=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        required=True,
        index=True,
    )
    credit_control_line_ids = fields.One2many(
        comodel_name='credit.control.line',
        inverse_name="communication_id",
        string='Credit Lines',
    )
    contact_address_id = fields.Many2one(
        comodel_name='res.partner',
        index=True,
    )
    report_date = fields.Date(
        default=lambda self: fields.Date.context_today(self),
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        default=lambda self: self._default_company(),
        required=True,
        index=True,
    )
    user_id = fields.Many2one(
        comodel_name='res.users',
        default=lambda self: self.env.user,
        string='User',
        index=True,
    )
    total_invoiced = fields.Float(
        compute='_compute_total',
    )
    total_due = fields.Float(
        compute='_compute_total',
    )

    @api.model
    def _default_company(self):
        company_obj = self.env['res.company']
        return company_obj._company_default_get('credit.control.policy')

    @api.model
    def _get_total(self):
        amount_field = 'credit_control_line_ids.amount_due'
        return sum(self.mapped(amount_field))

    @api.model
    def _get_total_due(self):
        balance_field = 'credit_control_line_ids.balance_due'
        return sum(self.mapped(balance_field))

    @api.multi
    @api.depends('credit_control_line_ids',
                 'credit_control_line_ids.amount_due',
                 'credit_control_line_ids.balance_due')
    def _compute_total(self):
        for communication in self:
            communication.total_invoiced = communication._get_total()
            communication.total_due = communication._get_total_due()

    @api.model
    def _onchange_partner_id(self):
        """Update address when partner changes."""
        for one in self:
            partners = one.env["res.partner"].search([
                ("id", "child_of", one.partner_id.id),
            ])
            if one.contact_address_id in partners:
                # Contact is already child of partner
                return
            address_ids = one.partner_id.address_get(adr_pref=['invoice'])
            one.contact_address_id = address_ids["invoice"]

    def get_emailing_contact(self):
        """Return a valid customer for the emailing. If the contact address
        doesn't have a valid email we fallback to the commercial partner"""
        self.ensure_one()
        contact = self.contact_address_id
        if not contact.email:
            contact = contact.commercial_partner_id
        return contact

    def get_email(self):
        """Kept for backwards compatibility. To be removed in v13/v14"""
        self.ensure_one()
        contact = self.get_emailing_contact()
        return contact and contact.email

    @api.model
    def _group_lines(self, lines):
        ordered_lines = lines.search(
            [("id", "in", lines.ids)],
            order="partner_id, currency_id, policy_id, state, level DESC",
        )
        prev_group = None
        prev_policy_level = None
        group_lines = self.env["credit.control.line"].browse()
        for line in ordered_lines:
            group = (line.partner_id, line.currency_id, line.policy_id, line.company_id)
            policy_level = line.policy_level_id
            if prev_group and (
                group != prev_group
                or (
                    not line.policy_id.auto_process_lower_levels and
                    policy_level != prev_policy_level
                )
            ):
                yield (
                    group_lines[0].partner_id,
                    group_lines[0].currency_id,
                    group_lines[0].policy_level_id,
                    group_lines[0].company_id,
                    group_lines,
                )
                group_lines = self.env["credit.control.line"].browse()
            if line not in group_lines:
                group_lines |= line._get_lower_related_lines() or line
            prev_group = group
            prev_policy_level = policy_level
        yield (
            group_lines[0].partner_id,
            group_lines[0].currency_id,
            group_lines[0].policy_level_id,
            group_lines[0].company_id,
            group_lines,
        )

    @api.model
    def _aggregate_credit_lines(self, lines):
        """ Aggregate credit control line by partner, level, and currency
        """
        comms = self.browse()
        if not lines:
            return comms
        company_currency = self.env.user.company_id.currency_id
        datas = []
        for (
            partner_id,
            currency_id,
            policy_level_id,
            company_id,
            grouped_lines,
        ) in self._group_lines(lines):
            data = {}
            data['credit_control_line_ids'] = [(6, 0, grouped_lines.ids)]
            data['partner_id'] = partner_id.id
            data['policy_level_id'] = policy_level_id.id
            data['currency_id'] = currency_id.id or company_currency.id
            data['company_id'] = company_id.id
            datas.append(data)
        return datas

    @api.model
    def _generate_comm_from_credit_lines(self, lines):
        """ Generate a communication object per aggregation of credit lines.
        """
        datas = self._aggregate_credit_lines(lines)
        comms = self.create(datas)
        comms._onchange_partner_id()
        return comms

    @api.multi
    def _generate_emails(self):
        """ Generate email message using template related to level """
        for comm in self:
            comm.message_post_with_template(
                comm.policy_level_id.email_template_id.id,
                composition_mode="mass_post",
                is_log=False,
                notify=True,
                subtype_id=self.env.ref("account_credit_control.mt_request").id,
            )
            comm.credit_control_line_ids \
                .filtered(lambda line: line.state == 'to_be_sent') \
                .write({"state": "queued"})

    @api.multi
    @api.returns('credit.control.line')
    def _mark_credit_line_as_sent(self):
        lines = self.mapped('credit_control_line_ids')
        lines.write({'state': 'sent'})
        return lines
