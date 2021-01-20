# Copyright 2021 ACSONE SA/NV
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


def migrate(cr, version):
    cr.execute(
        """
            UPDATE credit_control_line
            SET state='queued'
            WHERE state='sending'
        """
    )
