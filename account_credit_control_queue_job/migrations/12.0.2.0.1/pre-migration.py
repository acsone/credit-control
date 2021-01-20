# Copyright 2021 ACSONE SA/NV
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(env, version):
    env["credit.control.line"].search([("state", "=", "sending")]).write(
        {"state": "queued"}
    )
