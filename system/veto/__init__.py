CLOSE_CODES = (
    "COLLECTION_DOCUMENTED",
    "BUSINESS_RECORDS_RECONCILE",
    "DOCUMENTED_EVENT",
    "INVOICE_MATCHES",
    "OWN_ACCOUNT",
    "GROUP_COMPANY",
    "THIRD_PARTY_DOCUMENTED",
    "REFUND_OF_EARLIER_PAYMENT",
    "RETURNING_CUSTOMER",
    "LIST_MATCH_DIFFERENT_PARTY",
    "WITHIN_PROFILE",
)
RFI_CODES = (
    "RFI_PURPOSE_DOCUMENTS",
    "RFI_BUSINESS_RECORDS",
    "RFI_SOURCE_OF_FUNDS",
    "RFI_COUNTERPARTY_DETAILS",
    "RFI_UPDATED_PROFILE",
)
ESC_CODES = (
    "ESC_MULE_ACTIVITY",
    "ESC_STRUCTURING",
    "ESC_UNEXPLAINED_FUNDS",
    "ESC_PASS_THROUGH",
    "ESC_INVOICE_MISMATCH",
    "ESC_HIGH_RISK_CORRIDOR",
    "ESC_ACCOUNT_MISUSE",
    "ESC_THIRD_PARTY_FUNDING",
    "ESC_EARLY_REDEMPTION",
    "ESC_LISTED_PARTY",
)
CODE_VERDICT = {}
for _c in CLOSE_CODES:
    CODE_VERDICT[_c] = "CLOSE"
for _c in RFI_CODES:
    CODE_VERDICT[_c] = "RFI"
for _c in ESC_CODES:
    CODE_VERDICT[_c] = "ESCALATE"

HR_FALLBACK = (
    "Afghanistan", "Belarus", "Democratic Republic of the Congo", "Haiti",
    "Iran", "Iraq", "Lebanon", "Libya", "Mali", "Myanmar", "North Korea",
    "Russia", "Somalia", "South Sudan", "Syria", "Venezuela", "Yemen",
)

INVOICE_TYPES = {
    "invoice", "dealer_invoice", "hospital_invoice", "supplier_invoice",
    "supplier_invoices", "carrier_invoice", "freight_invoices",
    "payment_file", "contract_schedule", "purchase_order",
}
EVENT_TYPES = {
    "solicitor_letter", "insurer_letter", "vehicle_sale_receipt", "sale_receipt",
    "settlement_letter", "completion_statement", "loan_agreement",
    "cancellation_confirmation",
}
REFUND_TYPES = {
    "venue_email", "credit_note", "deposit_return_letter", "cancellation_confirmation",
}
