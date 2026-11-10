"""
ShopBase mock data generator -> inserts straight into your Supabase Postgres (public schema).

Setup:   pip install psycopg2-binary python-dotenv
Config:  put DATABASE_URL in a .env file (Supabase "Session pooler" connection string)

Usage:
    python generate_shopbase_data.py --dry-run     # build + validate in memory, touch nothing
    python generate_shopbase_data.py               # clean data
    python generate_shopbase_data.py --dirty       # adds data quality problems to practice on
    python generate_shopbase_data.py --clean-only  # delete all mock data and stop

Every mock business is named "[MOCK] ...". Re-running first deletes the previous mock data,
so it is safe to run repeatedly and it never touches your real businesses.
Everything is inserted in ONE transaction: it either fully succeeds or nothing changes.
"""
import argparse
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from itertools import accumulate

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ap = argparse.ArgumentParser()
ap.add_argument("--businesses", type=int, default=2)
ap.add_argument("--inventories", type=int, default=4, help="branches per business")
ap.add_argument("--products", type=int, default=80, help="per business")
ap.add_argument("--customers", type=int, default=500, help="per business")
ap.add_argument("--sales", type=int, default=12000, help="per business")
ap.add_argument("--months", type=int, default=12)
ap.add_argument("--owner-id", help="auth.users id; default = first user in auth.users")
ap.add_argument("--dirty", action="store_true")
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--clean-only", action="store_true")
ap.add_argument("--seed", type=int, default=42)
args = ap.parse_args()

rng = random.Random(args.seed)
NOW = datetime.now(timezone.utc).replace(microsecond=0)
START = NOW - timedelta(days=30 * args.months)


def uid():
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


# ------------------------------------------------------------------ reference data
BIZ_NAMES = ["Noor Perfumes", "Layali Beauty", "Cedar Cosmetics", "Amber House"]
BRANCHES = ["Beirut - Hamra", "Beirut - Achrafieh", "Tripoli", "Sidon",
            "Jounieh", "Zahle", "Tyre", "Byblos"]
CATEGORIES = ["Perfume", "Oud & Bakhoor", "Skincare", "Makeup", "Hair Care", "Gift Sets"]
BRANDS = ["Aurelia", "Nafas", "Layali", "Zahra", "Maison Noor", "Sahara", "Rimal", "Duha"]
ADJ = ["Royal", "Midnight", "Golden", "Velvet", "Amber", "Rose", "Silk", "Desert", "Pure", "Intense"]
NOUN = ["Oud", "Musk", "Jasmine", "Saffron", "Sandalwood", "Bloom", "Mist", "Essence", "Elixir", "Glow"]
FIRST = ["Ahmad", "Mohammad", "Ali", "Hassan", "Karim", "Rami", "Omar", "Elie", "Georges", "Tarek",
         "Sara", "Nour", "Lina", "Maya", "Rima", "Hala", "Dana", "Layla", "Nadine", "Joelle"]
LAST = ["Khoury", "Haddad", "Nasser", "Saad", "Mansour", "Fares", "Hamdan", "Karam",
        "Salameh", "Abboud", "Daher", "Issa"]
TAGS = [("VIP", "manual"), ("Wholesale", "manual"), ("Frequent buyer", "auto"), ("Debtor", "auto")]

# exchange rate drifts a little month to month
RATES = [89500]
for _ in range(args.months + 3):
    RATES.append(RATES[-1] + rng.choice([-250, 0, 0, 250, 500]))


def rate_for(dt):
    i = max(0, min(int((dt - START).days // 30), len(RATES) - 1))
    return RATES[i]


def rand_dt():
    """More sales recently (growth), busier Fri/Sat, evening peak."""
    span = (NOW - START).total_seconds()
    while True:
        dt = START + timedelta(seconds=(rng.random() ** 0.75) * span)
        if dt.weekday() in (4, 5) or rng.random() > 0.3:
            break
    hour = rng.choices(range(9, 22), [2, 4, 6, 6, 5, 5, 6, 8, 9, 8, 6, 3, 1])[0]
    dt = dt.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59), microsecond=0)
    if dt > NOW:
        dt = NOW - timedelta(minutes=rng.randint(1, 600))
    return dt


def phone():
    return f"+961{rng.choice(['3', '70', '71', '76', '78', '79', '81'])}{rng.randint(100000, 999999)}"


# ------------------------------------------------------------------ build in memory
def build(owner_id):
    D = {t: [] for t in ["businesses", "inventories", "products", "inventory_stock", "customers",
                         "tags", "customer_tags", "sales", "sale_items", "payments", "expenses",
                         "stock_transfers", "stock_transfer_items"]}

    for b in range(args.businesses):
        bid = uid()
        D["businesses"].append(dict(
            id=bid, owner_id=owner_id, name=f"[MOCK] {BIZ_NAMES[b % len(BIZ_NAMES)]}",
            currency_rate=RATES[-1], currency_rate_updated_at=NOW,
            created_at=START - timedelta(days=60), business_type="perfume_cosmetics"))

        # inventories (= branches)
        invs = []
        for i in range(args.inventories):
            inv = dict(id=uid(), business_id=bid,
                       name=BRANCHES[(b * args.inventories + i) % len(BRANCHES)],
                       is_archived=False, created_at=START - timedelta(days=50), updated_at=NOW)
            invs.append(inv)
            D["inventories"].append(inv)
        inv_weight = list(accumulate([max(1, 8 - 2 * i) for i in range(len(invs))]))

        # products
        prods = []
        for i in range(args.products):
            sell = float(rng.choice([6, 9, 12, 15, 19, 25, 32, 45, 60, 85, 120])) + rng.choice([0, 0.5, 0.99])
            p = dict(id=uid(), business_id=bid,
                     name=f"{rng.choice(BRANDS)} {rng.choice(ADJ)} {rng.choice(NOUN)}",
                     sku=f"B{b + 1}-{i + 1:04d}", category=rng.choice(CATEGORIES),
                     cost_price_usd=round(sell * rng.uniform(0.4, 0.7), 2),
                     sell_price_usd=round(sell, 2), quantity=0,
                     low_stock_threshold=rng.choice([3, 5, 5, 10]),
                     created_at=START - timedelta(days=rng.randint(0, 200)), updated_at=NOW)
            prods.append(p)
            D["products"].append(p)
        pop = [rng.paretovariate(1.5) for _ in prods]   # a few best sellers, long tail

        # per-inventory stock
        stocked = {}
        for inv in invs:
            lst, w = [], []
            for p, pw in zip(prods, pop):
                if rng.random() < 0.85:
                    qty = rng.randint(0, 120)
                    D["inventory_stock"].append(dict(
                        product_id=p["id"], inventory_id=inv["id"], quantity=qty,
                        sell_price_usd=p["sell_price_usd"], cost_price_usd=p["cost_price_usd"],
                        low_stock_threshold=p["low_stock_threshold"], updated_at=NOW))
                    p["quantity"] += qty
                    lst.append(p)
                    w.append(pw)
            stocked[inv["id"]] = (lst, list(accumulate(w)))

        # customers
        custs = []
        for _ in range(args.customers):
            c = dict(id=uid(), business_id=bid, name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                     phone=phone(), created_at=START - timedelta(days=rng.randint(0, 365)))
            custs.append(c)
            D["customers"].append(c)

        # sales + items
        spend, credit_total, first_credit = {}, {}, {}
        for _ in range(args.sales):
            dt = rand_dt()
            inv = rng.choices(invs, cum_weights=inv_weight)[0]
            cust = rng.choice(custs) if rng.random() < 0.55 else None
            ptype = "credit" if (cust and rng.random() < 0.3) else "cash"
            lst, cw = stocked[inv["id"]]
            sid, total = uid(), 0.0
            for p in rng.choices(lst, cum_weights=cw, k=rng.choices([1, 2, 3, 4, 5], [40, 30, 18, 8, 4])[0]):
                qty = rng.choices([1, 2, 3], [80, 15, 5])[0]
                sub = round(qty * p["sell_price_usd"], 2)
                total += sub
                D["sale_items"].append(dict(
                    id=uid(), sale_id=sid, product_id=p["id"], product_name_snapshot=p["name"],
                    quantity=qty, unit_price_usd=p["sell_price_usd"], subtotal_usd=sub,
                    cost_price_usd_snapshot=p["cost_price_usd"]))
            total, rate = round(total, 2), rate_for(dt)
            D["sales"].append(dict(
                id=sid, business_id=bid, customer_id=cust["id"] if cust else None,
                total_usd=total, total_lbp=round(total * rate), exchange_rate_used=rate,
                payment_type=ptype, created_at=dt, inventory_id=inv["id"]))
            if cust:
                spend[cust["id"]] = spend.get(cust["id"], 0) + total
                if ptype == "credit":
                    credit_total[cust["id"]] = credit_total.get(cust["id"], 0) + total
                    first_credit[cust["id"]] = min(first_credit.get(cust["id"], dt), dt)

        # customer payments on credit (some customers never pay = debtors)
        debtors = set()
        for cid, tot in credit_total.items():
            frac = rng.choice([0, 0.3, 0.5, 0.8, 1.0])
            if frac < 1:
                debtors.add(cid)
            if frac == 0:
                continue
            n = rng.randint(1, 3)
            for _ in range(n):
                span = max(1, int((NOW - first_credit[cid]).total_seconds()))
                D["payments"].append(dict(
                    id=uid(), customer_id=cid, amount_usd=round(tot * frac / n, 2),
                    note=rng.choice(["cash payment", "partial payment", "settled", None]),
                    created_at=first_credit[cid] + timedelta(seconds=rng.randint(60, span))))

        # tags
        tag_ids = {}
        for label, src in TAGS:
            tid = uid()
            tag_ids[label] = tid
            D["tags"].append(dict(id=tid, business_id=bid, label=label, source=src, created_at=START))
        ranked = sorted(spend, key=spend.get, reverse=True)
        assigned = set()

        def tag(cid, label):
            if (cid, label) not in assigned:
                assigned.add((cid, label))
                D["customer_tags"].append(dict(id=uid(), customer_id=cid, tag_id=tag_ids[label], created_at=NOW))
        for cid in ranked[:max(1, len(ranked) // 12)]:
            tag(cid, "VIP")
        for cid in ranked[:len(ranked) // 4]:
            tag(cid, "Frequent buyer")
        for cid in sorted(debtors):
            tag(cid, "Debtor")
        for c in rng.sample(custs, max(1, len(custs) // 30)):
            tag(c["id"], "Wholesale")

        # expenses: monthly recurring per branch + a few one-offs
        for m in range(args.months):
            for inv in invs:
                for label, lo, hi in [("Rent", 800, 1500), ("Electricity", 150, 400), ("Salaries", 1200, 2500)]:
                    D["expenses"].append(dict(
                        id=uid(), business_id=bid, label=label, amount_usd=round(rng.uniform(lo, hi), 2),
                        is_recurring=True, created_at=START + timedelta(days=30 * m + rng.randint(0, 4)),
                        inventory_id=inv["id"]))
        for _ in range(8):
            D["expenses"].append(dict(
                id=uid(), business_id=bid, label=rng.choice(["Packaging", "Marketing", "Maintenance", "Shop sign"]),
                amount_usd=round(rng.uniform(50, 600), 2), is_recurring=False,
                created_at=rand_dt(), inventory_id=rng.choice([i["id"] for i in invs] + [None])))

        # stock transfers between branches
        for _ in range(30):
            a, c = rng.sample(invs, 2)
            tid = uid()
            D["stock_transfers"].append(dict(id=tid, business_id=bid, from_inventory_id=a["id"],
                                             to_inventory_id=c["id"], created_by=owner_id, created_at=rand_dt()))
            for p in rng.sample(stocked[a["id"]][0], rng.randint(1, 4)):
                D["stock_transfer_items"].append(dict(
                    id=uid(), transfer_id=tid, product_id=p["id"], quantity=rng.randint(1, 20),
                    product_name_snapshot=p["name"]))
    return D


# ------------------------------------------------------------------ dirty data (respects DB constraints)
def make_dirty(D):
    n = {}
    # customers: duplicates, missing / inconsistent phones, messy names
    dups = []
    for c in rng.sample(D["customers"], len(D["customers"]) // 50):
        d = dict(c)
        d["id"] = uid()
        d["name"] = c["name"].upper()
        d["created_at"] = c["created_at"] + timedelta(days=rng.randint(1, 100))
        dups.append(d)
    D["customers"].extend(dups)
    n["duplicate customers"] = len(dups)
    for c in D["customers"]:
        r = rng.random()
        if r < 0.04:
            c["phone"] = None
        elif r < 0.08 and c["phone"]:
            c["phone"] = "0" + c["phone"][4:]          # local format instead of +961
        elif r < 0.10:
            c["name"] = "  " + c["name"].lower() + " "  # whitespace + casing
    # sales: header total != sum of items, future dates, wrong exchange rate
    for s in rng.sample(D["sales"], max(1, len(D["sales"]) // 300)):
        s["total_usd"] = round(s["total_usd"] + rng.uniform(1, 20), 2)
    for s in rng.sample(D["sales"], max(1, len(D["sales"]) // 300)):
        s["created_at"] = NOW + timedelta(days=rng.randint(10, 90))
    for s in rng.sample(D["sales"], max(1, len(D["sales"]) // 500)):
        s["exchange_rate_used"] = 895                   # missing zeros, total_lbp now inconsistent
    # sale items: subtotal != qty * price, orphaned product reference
    for it in rng.sample(D["sale_items"], max(1, len(D["sale_items"]) // 300)):
        it["subtotal_usd"] = round(it["subtotal_usd"] * 1.1, 2)
    for it in rng.sample(D["sale_items"], max(1, len(D["sale_items"]) // 200)):
        it["product_id"] = None
    # products: zero price, missing sku, inconsistent category casing
    for p in rng.sample(D["products"], 3):
        p["sell_price_usd"] = 0
    for p in rng.sample(D["products"], 3):
        p["sku"] = None
    for p in rng.sample(D["products"], len(D["products"]) // 15):
        p["category"] = p["category"].lower()
    print("Dirty mode: duplicate/messy customers, bad phones, total mismatches, future-dated sales,")
    print("            wrong exchange rates, bad subtotals, null product refs, zero prices, mixed casing")


# ------------------------------------------------------------------ validation (clean mode)
def validate(D):
    sums = {}
    for it in D["sale_items"]:
        sums[it["sale_id"]] = round(sums.get(it["sale_id"], 0) + it["subtotal_usd"], 2)
    bad = [s for s in D["sales"] if abs(s["total_usd"] - sums[s["id"]]) > 0.02]
    assert not bad, f"{len(bad)} sales whose total != sum of items"
    assert all(r["quantity"] >= 0 for r in D["inventory_stock"]), "negative stock"
    assert all(s["payment_type"] in ("cash", "credit") for s in D["sales"])
    assert all(s["customer_id"] for s in D["sales"] if s["payment_type"] == "credit")
    assert all(t["from_inventory_id"] != t["to_inventory_id"] for t in D["stock_transfers"])
    assert all(i["quantity"] > 0 for i in D["stock_transfer_items"])
    print("Validation passed: totals reconcile, constraints respected.")


# ------------------------------------------------------------------ database
COLS = {
    "businesses": ["id", "owner_id", "name", "currency_rate", "currency_rate_updated_at", "created_at", "business_type"],
    "inventories": ["id", "business_id", "name", "is_archived", "created_at", "updated_at"],
    "products": ["id", "business_id", "name", "sku", "category", "cost_price_usd", "sell_price_usd",
                 "quantity", "low_stock_threshold", "created_at", "updated_at"],
    "inventory_stock": ["product_id", "inventory_id", "quantity", "sell_price_usd", "cost_price_usd",
                        "low_stock_threshold", "updated_at"],
    "customers": ["id", "business_id", "name", "phone", "created_at"],
    "tags": ["id", "business_id", "label", "source", "created_at"],
    "customer_tags": ["id", "customer_id", "tag_id", "created_at"],
    "sales": ["id", "business_id", "customer_id", "total_usd", "total_lbp", "exchange_rate_used",
              "payment_type", "created_at", "inventory_id"],
    "sale_items": ["id", "sale_id", "product_id", "product_name_snapshot", "quantity", "unit_price_usd",
                   "subtotal_usd", "cost_price_usd_snapshot"],
    "payments": ["id", "customer_id", "amount_usd", "note", "created_at"],
    "expenses": ["id", "business_id", "label", "amount_usd", "is_recurring", "created_at", "inventory_id"],
    "stock_transfers": ["id", "business_id", "from_inventory_id", "to_inventory_id", "created_by", "created_at"],
    "stock_transfer_items": ["id", "transfer_id", "product_id", "quantity", "product_name_snapshot"],
}  # insertion order = dict order (parents before children)

B = "business_id = any(%s::uuid[])"
INV = "(select id from public.inventories where " + B + ")"
CUS = "(select id from public.customers where " + B + ")"
SAL = "(select id from public.sales where " + B + ")"
TRF = "(select id from public.stock_transfers where " + B + ")"
PRD = "(select id from public.products where " + B + ")"
TAG = "(select id from public.tags where " + B + ")"

# NOTE: while triggers are disabled, ON DELETE CASCADE does NOT fire (it is implemented with triggers).
# So every child table is deleted explicitly, children before parents.
CLEAN_SQL = [
    f"delete from public.payments where customer_id in {CUS}",
    f"delete from public.customer_tags where customer_id in {CUS} or tag_id in {TAG}",
    f"delete from public.sale_items where sale_id in {SAL}",
    f"delete from public.sales where {B}",
    f"delete from public.expenses where {B}",
    f"delete from public.stock_transfer_items where transfer_id in {TRF}",
    f"delete from public.stock_transfers where {B}",
    f"delete from public.stock_discrepancies where {B}",
    f"delete from public.applied_stock_operations where product_id in {PRD} or inventory_id in {INV}",
    f"delete from public.inventory_stock where inventory_id in {INV} or product_id in {PRD}",
    f"delete from public.customers where {B}",
    f"delete from public.tags where {B}",
    f"delete from public.products where {B}",
    f"delete from public.inventories where {B}",
    "delete from public.businesses where id = any(%s::uuid[])",
]

# Sweep leftovers (rows whose parent no longer exists) from earlier runs. A healthy database can
# never contain these because foreign keys forbid them, so this only removes our own leftovers.
ORPHAN_SQL = [
    "delete from public.payments where customer_id not in (select id from public.customers)",
    "delete from public.customer_tags where customer_id not in (select id from public.customers) or tag_id not in (select id from public.tags)",
    "delete from public.sale_items where sale_id not in (select id from public.sales)",
    "delete from public.stock_transfer_items where transfer_id not in (select id from public.stock_transfers)",
    "delete from public.applied_stock_operations where product_id not in (select id from public.products)",
    "delete from public.inventory_stock where product_id not in (select id from public.products) or inventory_id not in (select id from public.inventories)",
    "delete from public.tags where business_id not in (select id from public.businesses)",
]


def clean_mock(cur):
    cur.execute("select id from public.businesses where name like %s", ("[MOCK]%",))
    ids = [r[0] for r in cur.fetchall()]
    for q in CLEAN_SQL if ids else []:
        cur.execute(q, (ids,) * q.count("%s"))
    swept = 0
    for q in ORPHAN_SQL:
        cur.execute(q)
        swept += cur.rowcount
    print(f"Removed previous mock data ({len(ids)} businesses)" + (f" and {swept} orphaned rows." if swept else "."))


def main():
    if args.dry_run:
        D = build(args.owner_id or uid())
        if args.dirty:
            make_dirty(D)
        else:
            validate(D)
        for t, rows in D.items():
            print(f"  {t:<22}{len(rows):>9,} rows")
        print("Dry run only: nothing was written.")
        return

    import psycopg2
    from psycopg2.extras import execute_values
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set. Put it in a .env file (see .env.example).")
    conn = psycopg2.connect(url)
    try:
        with conn, conn.cursor() as cur:       # one transaction: all or nothing
            # We insert the FINAL state ourselves, so stop the app's own triggers (e.g. auto-creating
            # stock rows, deducting stock on sale) from firing and duplicating/altering our data.
            cur.execute("savepoint trg")
            try:
                cur.execute("set local session_replication_role = replica")
                print("App triggers disabled for this transaction only.")
            except psycopg2.Error as e:
                cur.execute("rollback to savepoint trg")
                print("Could not disable triggers (" + (e.pgerror or str(e)).strip() + "); using ON CONFLICT fallback.")
            clean_mock(cur)
            if args.clean_only:
                return
            owner = args.owner_id
            if not owner:
                cur.execute("select id from auth.users order by created_at limit 1")
                row = cur.fetchone()
                if not row:
                    sys.exit("No users in auth.users. Sign up once in your app (or add a user in "
                             "Supabase > Authentication), or pass --owner-id.")
                owner = str(row[0])
            D = build(owner)
            if args.dirty:
                make_dirty(D)
            else:
                validate(D)
            for t, cols in COLS.items():
                rows = [tuple(r[c] for c in cols) for r in D[t]]
                sql = f"insert into public.{t} ({', '.join(cols)}) values %s"
                if t == "inventory_stock":   # safety net if a DB trigger already created these rows
                    sql += (" on conflict (product_id, inventory_id) do update set quantity = excluded.quantity,"
                            " sell_price_usd = excluded.sell_price_usd, cost_price_usd = excluded.cost_price_usd,"
                            " low_stock_threshold = excluded.low_stock_threshold, updated_at = excluded.updated_at")
                execute_values(cur, sql, rows, page_size=2000)
                print(f"  inserted {t:<22}{len(rows):>9,} rows")
        print("Done. Committed.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()