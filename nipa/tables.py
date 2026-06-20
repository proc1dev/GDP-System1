"""
NIPA accounting trees for the main BEA tables.

Each function returns the root NIPANode of a tree whose edges encode the
accounting identity   parent = Σ sign_i × child_i.

Tables implemented
------------------
T10105  Table 1.1.5   GDP (nominal, current dollars, SAAR)
T10106  Table 1.1.6   GDP (real, chained 2017 dollars, SAAR)
T10705  Table 1.7.5   Relation of GDP → GNP → NNP → NI → PI → DPI → PCE
T20100  Table 2.1     Personal Income and Its Disposition

BEA series codes can be verified at:
    https://apps.bea.gov/api/data/?method=GetParameterValues
    &datasetname=NIPA&ParameterName=SeriesCode
"""

from .node import NIPANode
from .series import NIPASeries

# --------------------------------------------------------------------------- #
# Helper — build a NIPASeries and wrap it immediately in a NIPANode
# --------------------------------------------------------------------------- #

def _s(
    code: str,
    name: str,
    table: str,
    line: int,
    is_nominal: bool = True,
    bbl_ticker: str | None = None,
) -> NIPANode:
    return NIPANode(
        NIPASeries(
            code=code,
            name=name,
            table=table,
            line=line,
            is_nominal=is_nominal,
            bbl_ticker=bbl_ticker,
        )
    )


# =========================================================================== #
# Table 1.1.5  –  Gross Domestic Product (Nominal)
# =========================================================================== #

def build_T10105() -> NIPANode:
    """
    GDP expenditure identity (nominal current dollars, SAAR):

        GDP = PCE + GPDI + NX + GCE
        NX  = Exports − Imports          ← Imports enter with sign −1
    """
    T = "1.1.5"

    # ── Leaves: PCE sub-components ──────────────────────────────────────── #
    pce_dur   = _s("DDURRC",  "Durable goods",                       T,  4)
    pce_ndur  = _s("DNDGRC",  "Nondurable goods",                    T,  5)
    pce_svc   = _s("DSERRC",  "Services",                            T,  6)
    pce_goods = _s("DGDSRC",  "Goods",                               T,  3)
    pce_goods.add(pce_dur).add(pce_ndur)

    pce = _s("DPCERC", "Personal Consumption Expenditures",          T,  2,
             bbl_ticker="PCE CQOQ Index")
    pce.add(pce_goods).add(pce_svc)

    # ── Leaves: Investment sub-components ───────────────────────────────── #
    ip_sw     = _s("Y002RC",  "Software",                            T, 13)
    ip_rd     = _s("Y010RC",  "Research and development",            T, 14)
    ip_ent    = _s("A014RC",  "Entertainment, literary, artistic",   T, 15)
    ip        = _s("Y001RC",  "Intellectual property products",      T, 12)
    ip.add(ip_sw).add(ip_rd).add(ip_ent)

    nonres_struct = _s("A009RC", "Structures",                       T, 10)
    nonres_equip  = _s("Y033RC", "Equipment",                        T, 11)
    nonres = _s("A008RC",  "Nonresidential",                         T,  9)
    nonres.add(nonres_struct).add(nonres_equip).add(ip)

    res_fixed = _s("A011RC",  "Residential",                         T, 16)
    fixed_inv = _s("A007RC",  "Fixed investment",                    T,  8)
    fixed_inv.add(nonres).add(res_fixed)

    inventories = _s("A019RC", "Change in private inventories",      T, 17)
    gpdi = _s("A006RC",  "Gross Private Domestic Investment",        T,  7,
              bbl_ticker="USGRFINV Index")
    gpdi.add(fixed_inv).add(inventories)

    # ── Leaves: Net exports ──────────────────────────────────────────────── #
    ex_goods = _s("A022RC",  "Goods (exports)",                      T, 20)
    ex_svc   = _s("A023RC",  "Services (exports)",                   T, 21)
    exports  = _s("A021RC",  "Exports",                              T, 19)
    exports.add(ex_goods).add(ex_svc)

    im_goods = _s("A025RC",  "Goods (imports)",                      T, 23)
    im_svc   = _s("A026RC",  "Services (imports)",                   T, 24)
    imports  = _s("A024RC",  "Imports",                              T, 22)
    imports.add(im_goods).add(im_svc)

    # NX = Exports − Imports  (imports sign = −1)
    net_exports = _s("A020RC", "Net exports of goods and services",  T, 18)
    net_exports.add(exports, sign=+1).add(imports, sign=-1)

    # ── Leaves: Government ──────────────────────────────────────────────── #
    fed_def_cons = _s("B826RC", "Defense consumption expenditures",  T, 28)
    fed_def_inv  = _s("B827RC", "Defense gross investment",          T, 29)
    fed_def      = _s("B823RC", "National defense",                  T, 27)
    fed_def.add(fed_def_cons).add(fed_def_inv)

    fed_nondef_cons = _s("B831RC", "Nondefense consumption exp.",    T, 31)
    fed_nondef_inv  = _s("B832RC", "Nondefense gross investment",    T, 32)
    fed_nondef      = _s("B828RC", "Nondefense",                     T, 30)
    fed_nondef.add(fed_nondef_cons).add(fed_nondef_inv)

    fed_gce = _s("A823RC",  "Federal",                               T, 26)
    fed_gce.add(fed_def).add(fed_nondef)

    sl_cons = _s("A832RC",  "State & local consumption exp.",        T, 34)
    sl_inv  = _s("A833RC",  "State & local gross investment",        T, 35)
    sl_gce  = _s("A829RC",  "State and local",                      T, 33)
    sl_gce.add(sl_cons).add(sl_inv)

    gce = _s("A822RC",
             "Government consumption expenditures and gross investment", T, 25)
    gce.add(fed_gce).add(sl_gce)

    # ── Root: GDP ────────────────────────────────────────────────────────── #
    gdp = _s("A191RC", "Gross Domestic Product",                     T,  1,
             bbl_ticker="GDP CQOQ Index")
    gdp.add(pce).add(gpdi).add(net_exports).add(gce)

    return gdp


# =========================================================================== #
# Table 1.1.6  –  Real Gross Domestic Product (Chained 2017 $)
# =========================================================================== #

def build_T10106() -> NIPANode:
    """
    Same expenditure structure as 1.1.5 but chained-dollar (real) series.

    Note: chain-weighted aggregation means identities do NOT hold exactly.
    The residual is the 'chain-weighting residual' (typically <$10B).
    Use tolerance=15 when validating real series.
    """
    T = "1.1.6"

    pce_dur   = _s("DDURRX",  "Durable goods (real)",               T,  4, False)
    pce_ndur  = _s("DNDGRX",  "Nondurable goods (real)",            T,  5, False)
    pce_svc   = _s("DSERRX",  "Services (real)",                    T,  6, False)
    pce_goods = _s("DGDSRX",  "Goods (real)",                       T,  3, False)
    pce_goods.add(pce_dur).add(pce_ndur)
    pce = _s("DPCERX", "Personal Consumption Expenditures (real)",  T,  2, False,
             bbl_ticker="PCE CHNG Index")
    pce.add(pce_goods).add(pce_svc)

    ip_sw  = _s("Y002RX", "Software (real)",                        T, 13, False)
    ip_rd  = _s("Y010RX", "R&D (real)",                             T, 14, False)
    ip_ent = _s("A014RX", "Entertainment (real)",                   T, 15, False)
    ip     = _s("Y001RX", "Intellectual property products (real)",  T, 12, False)
    ip.add(ip_sw).add(ip_rd).add(ip_ent)

    nonres_struct = _s("A009RX", "Structures (real)",               T, 10, False)
    nonres_equip  = _s("Y033RX", "Equipment (real)",                T, 11, False)
    nonres = _s("A008RX", "Nonresidential (real)",                  T,  9, False)
    nonres.add(nonres_struct).add(nonres_equip).add(ip)

    res_fixed = _s("A011RX", "Residential (real)",                  T, 16, False)
    fixed_inv = _s("A007RX", "Fixed investment (real)",             T,  8, False)
    fixed_inv.add(nonres).add(res_fixed)

    inventories = _s("A019RD", "Change in inventories (real)",      T, 17, False)
    gpdi = _s("A006RX", "GPDI (real)",                              T,  7, False)
    gpdi.add(fixed_inv).add(inventories)

    ex_goods = _s("A022RX", "Goods exports (real)",                 T, 20, False)
    ex_svc   = _s("A023RX", "Services exports (real)",              T, 21, False)
    exports  = _s("A021RX", "Exports (real)",                       T, 19, False)
    exports.add(ex_goods).add(ex_svc)

    im_goods = _s("A025RX", "Goods imports (real)",                 T, 23, False)
    im_svc   = _s("A026RX", "Services imports (real)",              T, 24, False)
    imports  = _s("A024RX", "Imports (real)",                       T, 22, False)
    imports.add(im_goods).add(im_svc)

    net_exports = _s("A020RX", "Net exports (real)",                T, 18, False)
    net_exports.add(exports, +1).add(imports, -1)

    fed_def_cons = _s("B826RX", "Defense consumption (real)",       T, 28, False)
    fed_def_inv  = _s("B827RX", "Defense investment (real)",        T, 29, False)
    fed_def      = _s("B823RX", "National defense (real)",          T, 27, False)
    fed_def.add(fed_def_cons).add(fed_def_inv)

    fed_nondef_cons = _s("B831RX", "Nondefense consumption (real)", T, 31, False)
    fed_nondef_inv  = _s("B832RX", "Nondefense investment (real)",  T, 32, False)
    fed_nondef      = _s("B828RX", "Nondefense (real)",             T, 30, False)
    fed_nondef.add(fed_nondef_cons).add(fed_nondef_inv)

    fed_gce = _s("A823RX", "Federal (real)",                        T, 26, False)
    fed_gce.add(fed_def).add(fed_nondef)

    sl_cons = _s("A832RX", "S&L consumption (real)",                T, 34, False)
    sl_inv  = _s("A833RX", "S&L investment (real)",                 T, 35, False)
    sl_gce  = _s("A829RX", "State and local (real)",                T, 33, False)
    sl_gce.add(sl_cons).add(sl_inv)

    gce = _s("A822RX", "Government exp. and investment (real)",     T, 25, False)
    gce.add(fed_gce).add(sl_gce)

    gdp = _s("A191RX", "Real Gross Domestic Product",               T,  1, False,
             bbl_ticker="GDP CHNG Index")
    gdp.add(pce).add(gpdi).add(net_exports).add(gce)

    return gdp


# =========================================================================== #
# Table 1.7.5  –  GDP → GNP → NNP → NI → PI → DPI → PCE
# =========================================================================== #

def build_T10705() -> NIPANode:
    """
    Income-side bridge table (nominal).

    Key identities:
        GNP  = GDP + Factor income from ROW − Factor income to ROW
        NNP  = GNP − Consumption of fixed capital
        NI   = NNP − Statistical discrepancy − Other adjustments
        PI   = NI  − Corporate profits − Net interest − ...  + Transfers
        DPI  = PI  − Personal current taxes
        PCE  = DPI − Personal saving − Other personal outlays
    """
    T = "1.7.5"

    # GDP (cross-reference to 1.1.5 root)
    gdp = _s("A191RC", "Gross Domestic Product",                         T,  1)

    # GDP → GNP
    income_from_row = _s("B020RC", "Plus: Income receipts from ROW",    T,  2)
    income_to_row   = _s("B021RC", "Less: Income payments to ROW",      T,  3)
    gnp = _s("A017RC", "Gross National Product",                         T,  4,
             bbl_ticker="USGDP Index")
    gnp.add(gdp).add(income_from_row, +1).add(income_to_row, -1)

    # GNP → NNP
    cfc = _s("A024RC1", "Less: Consumption of fixed capital",           T,  5)
    nnp = _s("B015RC",  "Net National Product",                         T,  6)
    nnp.add(gnp).add(cfc, -1)

    # NNP → NI (statistical discrepancy, business transfers, etc.)
    stat_disc  = _s("A019RCD", "Less: Statistical discrepancy",         T,  7)
    other_adj  = _s("A020RCD", "Plus: Other adjustments",               T,  8)
    ni = _s("A032RC",  "National Income",                               T,  9)
    ni.add(nnp).add(stat_disc, -1).add(other_adj, +1)

    # NI → PI (complex bridge: subtract retained earnings, add transfers)
    corp_profits    = _s("A053RC", "Less: Corporate profits",           T, 10)
    net_interest    = _s("A063RC", "Less: Net interest",                T, 11)
    ni_taxes        = _s("A061RC", "Less: Taxes on prod. and imports",  T, 12)
    contributions   = _s("W825RC", "Less: Contributions social ins.",   T, 13)
    net_dividends   = _s("B054RC", "Plus: Dividends",                   T, 14)
    transfers       = _s("A063RCB","Plus: Personal transfer receipts",  T, 15)
    pi = _s("A065RC", "Personal Income",                                T, 16)
    pi.add(ni)
    pi.add(corp_profits, -1)
    pi.add(net_interest, -1)
    pi.add(ni_taxes, -1)
    pi.add(contributions, -1)
    pi.add(net_dividends, +1)
    pi.add(transfers, +1)

    # PI → DPI
    pers_taxes = _s("A061RC1", "Less: Personal current taxes",         T, 17)
    dpi = _s("A067RC", "Disposable Personal Income",                   T, 18)
    dpi.add(pi).add(pers_taxes, -1)

    # DPI → PCE + Personal Saving + Other outlays
    pce_ref      = _s("DPCERC",  "Personal Consumption Expenditures",  T, 19)
    pers_saving  = _s("A071RC",  "Personal saving",                    T, 20)
    other_outlays= _s("A072RC",  "Other personal outlays",             T, 21)
    # (DPI is the parent; PCE, saving, other outlays are children)
    dpi.add(pce_ref, -1)   # this is a check node — DPI = PCE + saving + other
    dpi.add(pers_saving, -1)
    dpi.add(other_outlays, -1)

    return gnp  # root of the bridge tree


# =========================================================================== #
# Table 2.1  –  Personal Income and Its Disposition
# =========================================================================== #

def build_T20100() -> NIPANode:
    """
    Personal Income identity (nominal):

        PI = Compensation
           + Proprietors' income (with IVA & CCadj)
           + Rental income (with CCadj)
           + Personal income receipts on assets
           + Personal current transfer receipts
           − Contributions for gov't social insurance

        DPI = PI − Personal current taxes

        PCE + Saving + Other outlays = DPI
    """
    T = "2.1"

    # ── Components of Personal Income ───────────────────────────────────── #
    wages_sal   = _s("A576RC",  "Wages and salaries",                   T,  3)
    supp_comp   = _s("A038RC",  "Supplements to wages",                 T,  4)
    compensation= _s("A033RC",  "Compensation of employees",            T,  2)
    compensation.add(wages_sal).add(supp_comp)

    prop_farm   = _s("A045RC",  "Farm",                                 T,  7)
    prop_nfarm  = _s("A048RC",  "Nonfarm",                              T,  8)
    prop_income = _s("A041RC",  "Proprietors' income (IVA & CCadj)",    T,  6)
    prop_income.add(prop_farm).add(prop_nfarm)

    rental      = _s("A048RC1", "Rental income (with CCadj)",           T,  9)

    dividends   = _s("B054RC",  "Dividends",                            T, 11)
    interest    = _s("A064RC",  "Personal interest income",             T, 12)
    asset_inc   = _s("A064RCB", "Personal income receipts on assets",   T, 10)
    asset_inc.add(dividends).add(interest)

    fed_trans   = _s("A063RC1", "Federal transfer receipts",            T, 15)
    sl_trans    = _s("A063RC2", "State & local transfer receipts",      T, 16)
    bus_trans   = _s("A063RC3", "Business transfer receipts",           T, 17)
    transfers   = _s("A063RCB", "Personal current transfer receipts",   T, 14)
    transfers.add(fed_trans).add(sl_trans).add(bus_trans)

    soc_ins     = _s("W825RC",  "Contrib. for gov't social insurance",  T, 18)

    pi = _s("A065RC", "Personal Income",                                T,  1)
    pi.add(compensation, +1)
    pi.add(prop_income, +1)
    pi.add(rental,      +1)
    pi.add(asset_inc,   +1)
    pi.add(transfers,   +1)
    pi.add(soc_ins,     -1)

    # ── Personal Income → Disposable Personal Income ─────────────────────── #
    pers_taxes = _s("A061RC1", "Personal current taxes",                T, 19)
    dpi = _s("A067RC", "Disposable Personal Income",                    T, 20)
    dpi.add(pi).add(pers_taxes, -1)

    # ── Uses of DPI ──────────────────────────────────────────────────────── #
    pce         = _s("DPCERC",  "Personal Consumption Expenditures",    T, 21)
    int_paid    = _s("A073RC",  "Personal interest payments",           T, 23)
    trans_paid  = _s("A074RC",  "Personal current transfer payments",   T, 24)
    other_out   = _s("A072RC",  "Other personal outlays",               T, 22)
    other_out.add(int_paid).add(trans_paid)
    saving      = _s("A071RC",  "Personal saving",                      T, 25)

    # Identity: DPI = PCE + other_outlays + saving
    dpi_uses    = _s("A067RC",  "Disposable Personal Income (uses)",    T, 20)
    dpi_uses.add(pce, +1).add(other_out, +1).add(saving, +1)

    return pi  # root


# =========================================================================== #
# Registry — all implemented tables
# =========================================================================== #

TABLES: dict[str, NIPANode] = {}

def _load_tables() -> None:
    TABLES["T10105"] = build_T10105()
    TABLES["T10106"] = build_T10106()
    TABLES["T10705"] = build_T10705()
    TABLES["T20100"] = build_T20100()


def get_table(table_id: str) -> NIPANode:
    """
    Return the root NIPANode for a table by its BEA table ID.

    Parameters
    ----------
    table_id : str — e.g. "T10105", "1.1.5", "T20100"
    """
    if not TABLES:
        _load_tables()
    # Accept both "T10105" and "1.1.5" style
    key = table_id.replace(".", "").upper()
    if not key.startswith("T"):
        key = "T" + key
    if key not in TABLES:
        raise KeyError(
            f"Table '{table_id}' not implemented. "
            f"Available: {list(TABLES.keys())}"
        )
    return TABLES[key]
