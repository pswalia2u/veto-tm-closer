import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

MONEY_RE = re.compile(r"£\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?|[0-9]+(?:\.[0-9]{2})?)")
FIELD_RE = re.compile(r"^\*\*(.+?):\*\*\s*(.*)$", re.M)
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b",
    re.I,
)
MY_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b",
    re.I,
)
ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
BORN_FULL_RE = re.compile(
    r"born\s+(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
    re.I,
)
ACCOUNT_RE = re.compile(r"\b(\d{2}-\d{2}-\d{2})\s+(\d{6,10})\b")
ENDING_RE = re.compile(r"(?:account|IBAN)\s+ending\s+(\d{3,4})", re.I)
SUFFIX_RE = re.compile(
    r"\b(limited|ltd|llp|plc|inc|incorporated|llc|company|co|sal|fze|bv|srl|gmbh|ag|"
    r"nv|oy|ab|spa|sarl|llc|corp|corporation)\b|sp\.?\s*z\.?\s*o\.?\s*o\.?",
    re.I,
)
PUNCT_RE = re.compile(r"[^a-z0-9]+")


def parse_money(s):
    if s is None:
        return None
    if isinstance(s, float):
        # Avoid Decimal(str(9680.129999999)) missing an exact pence match.
        try:
            return Decimal(format(s, ".2f"))
        except (InvalidOperation, ValueError):
            return None
    if isinstance(s, (int, Decimal)):
        return Decimal(s).quantize(Decimal("0.01"))
    s = str(s).strip()
    s = s.replace("£", "").replace(",", "").strip()
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def money_in_text(text):
    out = []
    for m in MONEY_RE.finditer(text or ""):
        v = parse_money(m.group(1))
        if v is not None:
            out.append(v)
    return out


def parse_date_parts(day, month, year):
    try:
        return date(int(year), MONTHS[month.lower()], int(day))
    except (ValueError, KeyError):
        return None


def parse_dates(text):
    found = []
    for m in DATE_RE.finditer(text or ""):
        d = parse_date_parts(m.group(1), m.group(2), m.group(3))
        if d:
            found.append(d)
    for m in ISO_RE.finditer(text or ""):
        try:
            found.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    return found


def parse_month_year(text):
    m = MY_RE.search(text or "")
    if not m:
        return None
    return (MONTHS[m.group(1).lower()], int(m.group(2)))


def dob_tuple_from_iso(s):
    if not s:
        return None
    try:
        d = datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
        return (d.month, d.year, d)
    except ValueError:
        return None


def norm_name(s):
    if not s:
        return ""
    s = s.lower()
    s = SUFFIX_RE.sub(" ", s)
    s = PUNCT_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # drop leftover legal particles
    toks = [t for t in s.split() if t not in {"the", "of", "and", "client", "account"}]
    return " ".join(toks)


def name_eq(a, b):
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if na in nb or nb in na:
        return True
    ta, tb = na.split(), nb.split()
    if len(ta) >= 2 and len(tb) >= 2 and ta[-2:] == tb[-2:]:
        return True
    if len(ta) >= 1 and len(tb) >= 1 and ta[0] == tb[0] and ta[-1] == tb[-1]:
        return True
    return False


def parse_md_fields(text):
    fields = {}
    for m in FIELD_RE.finditer(text or ""):
        fields[m.group(1).strip().lower()] = m.group(2).strip()
    return fields


def _split_row(line):
    parts = [p.strip() for p in line.strip().strip("|").split("|")]
    return parts


def parse_tables(text):
    tables = []
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        if "|" in lines[i] and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{3,}", lines[i + 1].replace(" ", "")):
            header = [h.lower() for h in _split_row(lines[i])]
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i] and not re.match(r"^\|?\s*:?-{3,}", lines[i].replace(" ", "")):
                rows.append(_split_row(lines[i]))
                i += 1
            tables.append((header, rows))
        else:
            i += 1
    return tables


def _cell(header, row, *names):
    for n in names:
        if n in header:
            idx = header.index(n)
            if idx < len(row):
                return row[idx]
    return ""


def parse_doc(ev):
    text = ev.get("text") or ""
    fields = parse_md_fields(text)
    tables = parse_tables(text)
    dtype = ev.get("type") or ""
    title = ev.get("title") or ""
    dated = None
    if ev.get("dated"):
        try:
            dated = datetime.strptime(ev["dated"][:10], "%Y-%m-%d").date()
        except ValueError:
            dated = None

    flags = {
        "fraud": dtype == "sending_bank_fraud_report" or "authorised push payment" in text.lower(),
        "threshold_evasion": False,
        "unwilling_lebanon": False,
        "shared_device": False,
        "nigeria_login": False,
        "hr_login": False,
        "mule_chat": False,
        "instalments": "instalment" in text.lower() or "four instalments" in text.lower(),
        "consultancy_goods": dtype in {"invoice", "supplier_invoice", "supplier_invoices"} and (
            "consultanc" in text.lower() or "market access" in text.lower()
        ),
        "electronics_hk": ("handset" in text.lower() or "electronics" in title.lower()) and (
            "hong kong" in text.lower() or " hk" in text.lower() or "HK" in title
        ),
    }
    low = text.lower()
    if dtype == "staff_note":
        if re.search(r"aggregat|below the £?10,?000|under £?10,?000|below £?1,?000|exempt", low):
            if re.search(r"invoice|report|identity|threshold", low):
                flags["threshold_evasion"] = True
            else:
                flags["threshold_evasion"] = True
        if "unwilling to explain" in low and "lebanon" in low:
            flags["unwilling_lebanon"] = True
    if dtype == "support_chat":
        if re.search(r"payments assistant|keep 8%|forward(?:ing)? (?:clients['’] )?money|i keep .*percent", low):
            flags["mule_chat"] = True
        if "family support" in low:
            flags["family_support"] = True

    officers = []
    psc = []
    group_companies = []
    device_customers = []
    login_countries = []
    travellers = []
    amount_roles = []

    for header, rows in tables:
        hset = set(header)
        if "officer" in hset:
            for row in rows:
                officers.append({
                    "name": _cell(header, row, "officer", "person"),
                    "role": _cell(header, row, "role"),
                    "born_my": parse_month_year(_cell(header, row, "born")),
                    "appointed": _parse_long_date(_cell(header, row, "appointed")),
                    "resigned": _parse_long_date(_cell(header, row, "resigned")),
                })
        if "person" in hset and ("control" in hset or "ceased" in hset):
            for row in rows:
                psc.append({
                    "name": _cell(header, row, "person", "person with significant control"),
                    "born_my": parse_month_year(_cell(header, row, "born")),
                    "ceased": _parse_long_date(_cell(header, row, "ceased")),
                    "control": _cell(header, row, "control"),
                })
        if "company" in hset and ("owner" in hset or "owner/owned by" in hset or "share" in hset):
            owner_key = "owner" if "owner" in header else ("owner/owned by" if "owner/owned by" in header else "")
            for row in rows:
                group_companies.append({
                    "company": _cell(header, row, "company"),
                    "owner": _cell(header, row, owner_key) if owner_key else "",
                })
        if "device" in hset:
            for row in rows:
                custs = _cell(header, row, "customers who logged in from it")
                device_customers.extend(re.findall(r"[A-Z]{2}-C\d+", custs))
                lc = _cell(header, row, "login countries")
                login_countries.extend([p.strip() for p in lc.split(",") if p.strip()])
        if "cash topped up" in hset:
            for row in rows:
                v = parse_money(_cell(header, row, "cash topped up"))
                if v is not None:
                    amount_roles.append({"role": "topup", "amount": v, "date": _parse_long_date(_cell(header, row, "date"))})
        if "total" in hset and "site" in hset:
            for row in rows:
                v = parse_money(_cell(header, row, "total"))
                if v is not None:
                    amount_roles.append({
                        "role": "collection_total",
                        "amount": v,
                        "site": _cell(header, row, "site"),
                        "date": _parse_long_date(_cell(header, row, "emptied")),
                    })
        if "cash counted" in hset:
            for row in rows:
                v = parse_money(_cell(header, row, "cash counted"))
                if v is not None:
                    amount_roles.append({"role": "cash_counted", "amount": v})
        if "amount" in hset and ("contractor" in hset or "payee" in hset or "stage" in hset or "invoice" in hset):
            name_key = "contractor" if "contractor" in header else (
                "payee" if "payee" in header else ("supplier" if "supplier" in header else "")
            )
            for row in rows:
                v = parse_money(_cell(header, row, "amount"))
                if v is None:
                    continue
                role = "stage" if "stage" in hset else ("invoice_row" if "invoice" in hset else "pay_row")
                amount_roles.append({
                    "role": role,
                    "amount": v,
                    "name": _cell(header, row, name_key) if name_key else _cell(header, row, "invoice"),
                    "date": _parse_long_date(_cell(header, row, "due", "dated")),
                    "ref": _cell(header, row, "invoice", "contract", "stage"),
                })

    if flags["instalments"] and dtype == "invoice":
        tot = parse_money(fields.get("total") or "")
        if tot is not None:
            amount_roles.append({"role": "instalment_total", "amount": tot})

    for key, role in (
        ("amount due", "due"),
        ("price", "price"),
        ("paid by bank transfer", "price"),
        ("amount", "amount"),
        ("total", "total"),
        ("principal amount", "principal"),
        ("total amount of credit", "principal"),
        ("paid to client's investment account", "paid_to_investment"),
        ("refund", "refund"),
    ):
        if key in fields:
            v = parse_money(fields[key])
            if v is not None:
                amount_roles.append({"role": role, "amount": v})

    # labelled prose amounts
    m = re.search(r"entitled share amounts to (£[0-9,]+(?:\.[0-9]{2})?)", text, re.I)
    if m:
        amount_roles.append({"role": "entitlement", "amount": parse_money(m.group(1))})
    m = re.search(r"(?:gift of|gifting the sum of|outright gift of)\s+(£[0-9,]+(?:\.[0-9]{2})?)", text, re.I)
    if m:
        amount_roles.append({"role": "gift", "amount": parse_money(m.group(1))})
    m = re.search(r"subscription of (£[0-9,]+(?:\.[0-9]{2})?)", text, re.I)
    if m:
        amount_roles.append({"role": "subscription", "amount": parse_money(m.group(1))})
    m = re.search(r"(?:purchase price|sum of|payment in the amount of|settlement of)\s+(£[0-9,]+(?:\.[0-9]{2})?)", text, re.I)
    if m:
        amount_roles.append({"role": "prose", "amount": parse_money(m.group(1))})
    m = re.search(r"£([0-9,]+(?:\.[0-9]{2})?)\s+per person,\s+£([0-9,]+(?:\.[0-9]{2})?)\s+in total", text, re.I)
    if m:
        amount_roles.append({"role": "per_person", "amount": parse_money(m.group(1))})
        amount_roles.append({"role": "booking_total", "amount": parse_money(m.group(2))})
    m = re.search(r"Advance at 85%:\s*(£[0-9,]+(?:\.[0-9]{2})?)", text, re.I)
    if m:
        amount_roles.append({"role": "advance", "amount": parse_money(m.group(1))})
    m = re.search(r"transfer of (£[0-9,]+(?:\.[0-9]{2})?)", text, re.I)
    if m:
        amount_roles.append({"role": "statement", "amount": parse_money(m.group(1))})
    m = re.search(r"received (£[0-9,]+(?:\.[0-9]{2})?)", text, re.I)
    if m and dtype == "bank_statement":
        amount_roles.append({"role": "statement", "amount": parse_money(m.group(1))})

    gift_donor = None
    gift_dob = None
    gm = re.search(
        r"I,\s+([^,\n]+?),\s+born\s+(\d{1,2}\s+\w+\s+\d{4})",
        text,
    )
    if gm:
        gift_donor = gm.group(1).strip()
        dd = DATE_RE.search(gm.group(2))
        if dd:
            gift_dob = parse_date_parts(dd.group(1), dd.group(2), dd.group(3))
    if not gift_donor:
        gm2 = re.search(r"I,\s+([^,\n]+?),\s+am writing", text)
        if gm2:
            gift_donor = gm2.group(1).strip()
    if not gift_donor and dtype == "gift_letter":
        hm = re.search(r"Gift letter from\s+(.+)", title, re.I)
        if hm:
            gift_donor = hm.group(1).strip()

    tm = re.search(r"Travellers:\s*((?:\n\d+\.\s+.+)*)", text)
    if tm:
        travellers = re.findall(r"\n\d+\.\s+(.+)", tm.group(0))

    pay_to = fields.get("pay to") or ""
    payee = pay_to.split(",")[0].strip() if pay_to else (fields.get("supplier") or fields.get("lender") or "")
    if dtype == "dealer_invoice":
        hm = re.search(r"from\s+(.+?)\s*$", title)
        if hm:
            payee = hm.group(1).strip()
    if dtype == "hospital_invoice" and "beirut" in low:
        payee = fields.get("pay to") or payee

    invoice_no = None
    im = re.search(r"\b([A-Z]{1,4}/?\d{3,6}|INV\s?\d{3,6}|PO\s?\d{3,6}|BOOKING\s+\w+|GT\d+)\b", title + " " + text)
    if im:
        invoice_no = im.group(1)

    if device_customers:
        flags["shared_device"] = len(set(device_customers)) >= 2
    for c in login_countries:
        cl = c.lower()
        if cl == "nigeria":
            flags["nigeria_login"] = True
        if cl in {
            "nigeria", "lebanon", "iraq", "iran", "syria", "russia", "haiti",
            "libya", "mali", "somalia", "yemen", "belarus", "myanmar",
        }:
            flags["hr_login"] = True

    names = []
    for k in ("bill to", "customer", "patient", "borrower", "lender", "account holder",
              "supplier", "buyer", "client", "pay to"):
        if k in fields:
            names.append(fields[k].split(",")[0].strip())
    if gift_donor:
        names.append(gift_donor)
    names.extend(travellers)

    return {
        "doc_id": ev.get("doc_id"),
        "type": dtype,
        "title": title,
        "dated": dated,
        "text": text,
        "fields": fields,
        "tables": tables,
        "flags": flags,
        "officers": officers,
        "psc": psc,
        "group_companies": group_companies,
        "device_customers": device_customers,
        "login_countries": login_countries,
        "travellers": [t.strip() for t in travellers],
        "amount_roles": [r for r in amount_roles if r.get("amount") is not None],
        "all_amounts": money_in_text(text),
        "gift_donor": gift_donor,
        "gift_dob": gift_dob,
        "payee": payee,
        "account_holder": fields.get("account holder") or "",
        "registered_office": fields.get("registered office") or "",
        "company": fields.get("company") or "",
        "invoice_no": invoice_no,
        "booking_ref": fields.get("booking reference") or "",
        "names": names,
    }


def _parse_long_date(s):
    if not s or not str(s).strip():
        return None
    m = DATE_RE.search(s)
    if m:
        return parse_date_parts(m.group(1), m.group(2), m.group(3))
    try:
        return datetime.strptime(str(s).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_docs(docs_raw):
    return [parse_doc(ev) for ev in docs_raw]


def tx_amount(tx):
    return parse_money(tx.get("amount_gbp"))


def tx_date(tx):
    s = (tx.get("booked_at") or "")[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None
