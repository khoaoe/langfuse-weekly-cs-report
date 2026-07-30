from __future__ import annotations

from html.parser import HTMLParser
from importlib import resources
import json
import re
import subprocess

from fastapi.testclient import TestClient

from weekly_cs_report.web import WebSettings, create_app


PAGE = resources.files("weekly_cs_report").joinpath("static/index.html")
REQUIRED_IDS = {
    "statusChip", "liveStatus", "updatedAt", "refreshButton", "weekDefinitionToggle",
    "sectionNav", "resetFiltersButton", "howToReadButton", "howToReadPanel",
    "dqBadge", "dqScoreValue", "dynamicTitle", "narrativeSummary", "activeFilterChips",
    "kpiGrid", "weeklyRows", "weeklyCopyButton", "weeklyCsvButton",
    "weeklyDefinitionsToggle", "weeklyDefinitionsPanel", "trendChart",
    "trendEmpty", "trendCaption", "segmentTabs", "segmentList",
    "segmentExpansionToggle", "segmentCaption", "segmentTabIssueCategory",
    "segmentTabApp", "segmentTabProductCode", "segmentTabIntent",
    "tpeDistribution", "guardrailDistribution", "escalationPanel", "unmappedTpePanel", "transferScope",
    "ruleGt4Panel", "ruleGt4Alert", "ruleScope", "coveragePanel", "qualityGrid", "gateGrid",
    "reopenReasons", "reopenReasonStatus", "reopenReasonCoverage",
    "reopenReasonControl", "reopenReasonCounts", "reopenReasonBusiness",
    "ticketFilters", "ticketRows", "ticketCsvButton", "ticketHeaderRow",
    "ticketColumnChooser", "ticketColumnOptions", "issueCategoryInput", "appInput",
    "productCodeInput", "skillInput", "intentInput", "tpeCodeInput",
    "gt4TurnInput", "transferredInput", "weekendInput",
}


class Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self.tags.append((tag, values))
        if values.get("id"):
            self.ids.add(str(values["id"]))


HARNESS = r"""
class Node {
  constructor(tag="div") { this.tagName=tag; this.children=[]; this.attributes={}; this.style={setProperty(k,v){this[k]=String(v)}}; this.hidden=false; this.disabled=false; this.value=""; this.id=""; this._text=""; this.className=""; this.namespaceURI=null; this._listeners={}; this._rect={height:0}; const classes=new Set();this.classList={add(...values){values.forEach(value=>classes.add(value))},remove(...values){values.forEach(value=>classes.delete(value))},toggle(value){if(classes.has(value)){classes.delete(value);return false}classes.add(value);return true},contains(value){return classes.has(value)}}; }
  get textContent(){ return this._text + this.children.map(x=>x.textContent).join(""); }
  set textContent(v){ this._text=String(v); this.children=[]; }
  appendChild(n){ this.children.push(n); return n; } append(...ns){ ns.forEach(n=>this.appendChild(n)); }
  setAttribute(k,v){this.attributes[k]=String(v);if(k==="id")this.id=String(v);} getAttribute(k){return this.attributes[k]||null;}
  addEventListener(type,handler){(this._listeners[type]??=[]).push(handler);} dispatchEvent(event){const value=event||{};value.target??=this;(this._listeners[value.type]||[]).forEach(handler=>handler(value));return true;} removeChild(n){this.children=this.children.filter(x=>x!==n);} click(){this.focus();this.dispatchEvent({type:"click"})} focus(){globalThis.document.activeElement=this;this.dispatchEvent({type:"focus"})} scrollIntoView(){} getBoundingClientRect(){return this._rect;}
}
const nodes=new Map();
const documentListeners={};
const topbar=new Node("header");topbar._rect={height:91};
globalThis.document={getElementById(id){if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);},createElement(t){return new Node(t);},createElementNS(n,t){const node=new Node(t);node.namespaceURI=n;return node;},createTextNode(t){const n=new Node("#text");n.textContent=t;return n;},querySelector(selector){return selector===".topbar"?topbar:selector.startsWith("#")?this.getElementById(selector.slice(1)):null;},querySelectorAll(){return [];},addEventListener(type,handler){(documentListeners[type]??=[]).push(handler);},dispatchEvent(event){(documentListeners[event.type]||[]).forEach(handler=>handler(event));return true;},documentElement:new Node("html"),activeElement:null,body:new Node("body")};
globalThis.window={setTimeout(){return 1},clearTimeout(){},matchMedia(){return {matches:false,addEventListener(){}}},scrollTo(){},ResizeObserver:class{constructor(callback){globalThis.__resizeCallback=callback;}observe(target){globalThis.__resizeTarget=target;}}};
globalThis.ResizeObserver=globalThis.window.ResizeObserver;
globalThis.navigator={clipboard:{writeText:async(v)=>globalThis.__copied=v}};
globalThis.URL={createObjectURL:()=>"blob:test",revokeObjectURL(){}};
"""


def page_text() -> str:
    assert PAGE.is_file()
    return PAGE.read_text(encoding="utf-8")


def run(page: str, scenario: str) -> dict[str, object]:
    script = re.search(r"<script>(.*?)</script>", page, re.S)
    assert script
    source = script.group(1)
    registration = 'document.addEventListener("DOMContentLoaded", initialise);'
    assert registration in source
    hooks = "globalThis.__test={applyEnvelope,renderDashboard,renderNarrative,renderKpis,renderWeeklyTable,weeklyValues,dateRange,setWeekDefinition,buildWeeklyExport,renderTransferReasons,renderTrend,renderSegments,renderDiagnostic,renderRules,renderQuality,renderReopenReason,postRefresh,setWeekFilter,setSegmentDimension,setSegmentFilter,toggleSegmentExpansion,updateFilters,buildTicketQuery,renderTickets,renderTicketColumnOptions,csvCell,exportTicketsCsv,syncStickyOffset:typeof syncStickyOffset===\"function\"?syncStickyOffset:null,setSnapshot(value){state.snapshot=value},setTicketPage(value){state.ticketPage=value},getTicketPage(){return state.ticketPage},setTicketColumns(value){state.ticketColumns=value},setTicketSort(field,direction){state.ticketSort={field,direction}}};"
    source = source.replace(registration, hooks + registration, 1)
    result = subprocess.run(["node", "-e", HARNESS + source + scenario], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_p4_dom_contract_and_security_surface():
    page = page_text()
    parser = Parser(); parser.feed(page)
    assert REQUIRED_IDS <= parser.ids
    assert all(path in page for path in ("/api/dashboard", "/api/tickets", "/api/refresh"))
    external_surface = page.replace("http://www.w3.org/2000/svg", "")
    assert "http://" not in external_surface.lower() and "https://" not in external_surface.lower()
    assert "innerHTML" not in page and "insertAdjacentHTML" not in page and "document.write" not in page
    forbidden_legacy_terms = ("AI " + "cover", "Full " + "AI")
    assert all(term not in page for term in forbidden_legacy_terms)
    assert "#0068FF" in page and "#111418" in page and "#E3E6EA" in page and "#F7F8FA" in page
    assert "#30343A" not in page and "#353A40" not in page
    assert ".status.good{color:var(--good-text)}" in page
    assert "prefers-color-scheme" in page and "prefers-reduced-motion" in page and ":focus-visible" in page
    assert any(tag == "table" for tag, _ in parser.tags)
    assert any(tag == "th" and attrs.get("scope") == "col" for tag, attrs in parser.tags)
    assert page.count(".style.") == 1
    assert 'document.documentElement.style.setProperty("--sticky-offset",`${height}px`)' in page
    assert not re.search(r"<[^>]+\sstyle=", page)


def test_page_does_not_embed_credentials_customer_text_or_internal_identifiers():
    lowered = page_text().lower()
    for forbidden in (
        "langfuse_secret_key", "langfuse_public_key", "langfuse_base_url",
        "customer_phone", "customer_email", "conversation_text", "raw_payload",
        "trace_id", "observation_id", "score_id", "0901234567", "9231",
    ):
        assert forbidden not in lowered


def test_fetches_only_same_origin_literal_api_routes():
    page = page_text()
    assert "fetch(url" not in page and "fetch(endpoint" not in page
    assert re.search(r'fetch\("/api/dashboard"', page)
    assert re.search(r'fetch\("/api/refresh"', page)
    assert "`/api/tickets?${query}`" in page


def test_refresh_uses_exact_same_origin_action_header():
    observed = run(page_text(), r"""
globalThis.fetch=async(url,options)=>{globalThis.__request={url,options};return {json:async()=>({status:"refreshing",snapshot:null})}};
(async()=>{await globalThis.__test.postRefresh();process.stdout.write(JSON.stringify(globalThis.__request))})().catch(error=>{process.stderr.write(String(error));process.exitCode=1});
""")
    assert observed["url"] == "/api/refresh"
    assert observed["options"]["method"] == "POST"
    assert observed["options"]["credentials"] == "same-origin"
    assert observed["options"]["headers"]["X-Dashboard-Action"] == "refresh"


def test_p4_uses_schema_views_transfer_contract_and_responsive_scroller():
    page = page_text()
    for token in ("state.snapshot.views[state.viewName]", "transfer_reasons", "by_week", "weekly-table-scroll", "Xem đủ cột", "font-variant-numeric"):
        assert token in page
    assert re.search(r"@media\s*\(max-width:\s*768px\)", page)
    assert re.search(r"\.weekly-table-scroll\s*\{[^}]*overflow-x:\s*auto", page, re.S)
    assert "line-reopen" in page and 'setAttribute("tabindex","0")' in page
    assert 'query.set("gt4_turn","true")' in page and 'query.set("transferred","false")' in page
    assert "Xem ${number(rule.gt4_turn_without_cs)} ticket" in page


def test_first_table_column_is_pinned_and_scroll_has_a_visible_hint():
    """Cuộn ngang mất nhãn tuần thì mọi ô số còn lại vô nghĩa."""
    page = page_text()
    assert re.search(r"\.weekly-table-scroll th:first-child[^{]*\{[^}]*position:sticky", page)
    assert re.search(r"\.weekly-table-scroll th:first-child[^{]*\{[^}]*left:0", page)
    assert re.search(r"\.explorer-table th:first-child", page)
    assert "background-attachment:local,local,scroll,scroll" in page


def test_p4_responsive_sticky_shell_measures_the_topbar_and_keeps_keyboard_focus_safe():
    page = page_text()
    assert 'id="skipToContent"' in page
    assert 'id="dashboardMain"' in page
    assert "function syncStickyOffset()" in page
    assert "ResizeObserver" in page
    assert "--sticky-offset:124px" not in page
    assert "--sticky-offset:232px" not in page

    observed = run(page, r"""
globalThis.fetch=async()=>({ok:true,json:async()=>({status:"ready",snapshot:null,items:[],page:1,page_size:50,total:0})});
document.dispatchEvent({type:"DOMContentLoaded"});
const initialOffset=document.documentElement.style["--sticky-offset"];
globalThis.__resizeTarget._rect={height:137};
globalThis.__resizeCallback([]);
const resizedOffset=document.documentElement.style["--sticky-offset"];
const help=document.getElementById("howToReadButton"),panel=document.getElementById("howToReadPanel");
panel.hidden=true;
help.dispatchEvent({type:"click"});
const opened=!panel.hidden&&document.activeElement===panel;
help.dispatchEvent({type:"click"});
const closed=panel.hidden&&document.activeElement===help;
document.getElementById("ticketIdInput").value="123";
document.getElementById("resetFiltersButton").dispatchEvent({type:"click"});
process.stdout.write(JSON.stringify({initialOffset,resizedOffset,opened,closed,ticketId:document.getElementById("ticketIdInput").value}));
""")
    assert observed == {
        "initialOffset": "91px", "resizedOffset": "137px", "opened": True,
        "closed": True, "ticketId": "",
    }


def test_p4_defers_sticky_table_headers_until_the_topbar_offset_is_measured():
    page = page_text()
    assert "th{position:static;top:auto" in page
    assert "html.sticky-offset-ready th{position:sticky;top:var(--sticky-offset)" in page

    observed = run(page, r"""
const before=document.documentElement.classList.contains("sticky-offset-ready");
globalThis.fetch=async()=>({ok:true,json:async()=>({status:"ready",snapshot:null,items:[],page:1,page_size:50,total:0})});
document.dispatchEvent({type:"DOMContentLoaded"});
process.stdout.write(JSON.stringify({before,after:document.documentElement.classList.contains("sticky-offset-ready"),offset:document.documentElement.style["--sticky-offset"]}));
""")
    assert observed == {"before": False, "after": True, "offset": "91px"}


def test_sticky_table_headers_pin_to_zero_inside_scroll_containers():
    """th sticky trong container overflow:auto phải top:0; offset của trang đẩy header vào giữa bảng."""
    page = page_text()
    assert "--table-sticky-top:0" in page
    assert "html.sticky-offset-ready th{position:sticky;top:var(--sticky-offset)" in page
    assert re.search(
        r"html\.sticky-offset-ready \.weekly-table-scroll th,"
        r"html\.sticky-offset-ready \.explorer-table th\{top:var\(--table-sticky-top\)\}",
        page,
    )
    assert page.count(".style.") == 1


def test_p4_skip_link_explicitly_moves_focus_to_dashboard_main():
    observed = run(page_text(), r"""
globalThis.fetch=async()=>({ok:true,json:async()=>({status:"ready",snapshot:null,items:[],page:1,page_size:50,total:0})});
document.dispatchEvent({type:"DOMContentLoaded"});
const skip=document.getElementById("skipToContent"),main=document.getElementById("dashboardMain");
skip.dispatchEvent({type:"click"});
process.stdout.write(JSON.stringify({focused:document.activeElement===main}));
""")
    assert observed == {"focused": True}


def test_p5_explorer_declares_exact_22_fields_filters_sort_columns_and_1000_row_export():
    page = page_text()
    expected_fields = (
        "ticket_id", "cohort_week", "cohort_status", "is_weekend_start", "outcome",
        "ai_first", "transferred", "reopen_lifetime", "reopen_within_7d",
        "ai_reply_count", "turn_count", "gt4_turn", "issue_category", "app",
        "product_code", "skill", "intent", "tpe_code", "tpe_status",
        "guardrail_rule", "escalation_guard_blocked", "data_quality",
    )
    declaration = re.search(r"const ticketFields=\[(.*?)\];", page, re.S)
    assert declaration
    assert tuple(re.findall(r'\["([^"]+)"\s*,', declaration.group(1))) == expected_fields
    for query_name in (
        "issue_category", "app", "product_code", "skill", "intent", "tpe_code",
        "gt4_turn", "transferred", "is_weekend_start",
    ):
        assert f'["{query_name}",' in page
    assert 'query.set("week_definition",state.viewName)' in page
    assert "query.set(name" in page
    assert "weekly-cs-ticket-columns-v1" in page
    assert "localStorage" in page
    assert "ticketSort" in page
    assert "1000" in page and 'page_size","100"' in page


def test_p5_explorer_builds_full_intersection_query_with_selected_week_definition():
    observed = run(page_text(), r"""
globalThis.__test.setWeekDefinition("mon_fri");
document.getElementById("ticketIdInput").value="123";
document.getElementById("outcomeInput").value="ai_end_to_end";
document.getElementById("issueCategoryInput").value="payment";
document.getElementById("appInput").value="zalopay";
document.getElementById("productCodeInput").value="IBFT";
document.getElementById("skillInput").value="ibft";
document.getElementById("intentInput").value="transfer_money";
document.getElementById("tpeCodeInput").value="-383";
document.getElementById("gt4TurnInput").value="true";
document.getElementById("transferredInput").value="false";
document.getElementById("weekendInput").value="false";
const query=Object.fromEntries(globalThis.__test.buildTicketQuery(2,100));
process.stdout.write(JSON.stringify(query));
""")
    assert observed == {
        "page": "2", "page_size": "100", "week_definition": "mon_fri",
        "ticket_id": "123", "outcome": "ai_end_to_end",
        "issue_category": "payment", "app": "zalopay", "product_code": "IBFT",
        "skill": "ibft", "intent": "transfer_money", "tpe_code": "-383",
        "gt4_turn": "true", "transferred": "false", "is_weekend_start": "false",
    }


def test_p5_explorer_renders_selected_columns_empty_state_and_client_sort():
    observed = run(page_text(), r"""
const row=(id,turn)=>({ticket_id:id,cohort_week:"2026-07-20",cohort_status:"complete",is_weekend_start:false,outcome:"ai_end_to_end",ai_first:true,transferred:false,reopen_lifetime:0,reopen_within_7d:0,ai_reply_count:1,turn_count:turn,gt4_turn:turn>4,issue_category:"payment",app:"zalopay",product_code:"IBFT",skill:"ibft",intent:"transfer_money",tpe_code:"-383",tpe_status:"Đang xử lý",guardrail_rule:null,escalation_guard_blocked:false,data_quality:"valid"});
globalThis.__test.setTicketColumns(["ticket_id","turn_count","issue_category"]);
globalThis.__test.setTicketSort("turn_count","desc");
globalThis.__test.renderTickets({items:[row("100",2),row("200",7)],page:1,page_size:50,total:2});
const first=document.getElementById("ticketRows").children[0].textContent;
const columns=document.getElementById("ticketHeaderRow").children.length;
globalThis.__test.renderTickets({items:[],page:1,page_size:50,total:0});
process.stdout.write(JSON.stringify({first,columns,empty:document.getElementById("ticketRows").textContent,formula:globalThis.__test.csvCell("-383")}));
""")
    assert observed["first"].startswith("2007payment")
    assert observed["columns"] == 3
    assert observed["empty"] == "Không có ticket phù hợp"
    assert observed["formula"] == "\"'-383\""


def test_p5_local_storage_persists_only_allowlisted_column_keys():
    page = page_text()
    assert page.count("localStorage.setItem(") == 1
    assert "localStorage.setItem(ticketColumnStorageKey,JSON.stringify(state.ticketColumns))" in page
    storage_call = page.split("localStorage.setItem(", 1)[1].split(")}", 1)[0]
    for forbidden in ("state.tickets", "ticketIdInput", "segmentFilter"):
        assert forbidden not in storage_call


def test_p5_csv_fetches_multiple_pages_caps_at_1000_and_uses_only_selected_fields():
    observed = run(page_text(), r"""
globalThis.__test.setSnapshot({generated_at:"2026-07-29T01:00:00Z"});
globalThis.URL.createObjectURL=(blob)=>{globalThis.__blob=blob;return "blob:test"};
globalThis.URL.revokeObjectURL=()=>{};
let requests=0;
const row=(id)=>({ticket_id:String(id),cohort_week:"2026-07-20",cohort_status:"complete",is_weekend_start:false,outcome:"ai_end_to_end",ai_first:true,transferred:false,reopen_lifetime:0,reopen_within_7d:0,ai_reply_count:1,turn_count:1,gt4_turn:false,issue_category:"payment",app:"zalopay",product_code:"IBFT",skill:"ibft",intent:"transfer_money",tpe_code:"-383",tpe_status:"Đang xử lý",guardrail_rule:null,escalation_guard_blocked:false,data_quality:"valid"});
globalThis.fetch=async(url)=>{requests+=1;const page=Number(String(url).match(/[?&]page=(\d+)/)[1]);return {ok:true,json:async()=>({items:Array.from({length:100},(_,index)=>row((page-1)*100+index+1)),page,page_size:100,total:1100})}};
(async()=>{await globalThis.__test.exportTicketsCsv();const csv=await globalThis.__blob.text();process.stdout.write(JSON.stringify({requests,lines:csv.split("\n").length,formulaSafe:csv.includes("'-383"),status:document.getElementById("liveStatus").textContent}))})().catch(error=>{process.stderr.write(String(error));process.exitCode=1});
""")
    assert observed["requests"] == 10
    assert observed["lines"] == 1002
    assert observed["formulaSafe"] is True
    assert "1.000 / 1.100" in observed["status"]


def test_view_toggle_updates_the_selected_weekly_view():
    observed = run(page_text(), r"""
const week=(count)=>({cohort_week:"2026-07-20",cohort_status:"complete",has_data:true,total_tickets:count,ai_first_count:count-1,ai_first_rate:(count-1)/count,ai_end_to_end_count:1,ai_then_cs_count:1,direct_cs_count:0,unclassified_count:0,reopen_lifetime_numerator:0,reopen_lifetime_rate:0,ai_reply_mean_ai_first:1,gt4_turn_with_cs:0,gt4_turn_without_cs:0,max_replies_rule_fired:0});
globalThis.__test.applyEnvelope({status:"ready",snapshot:{generated_at:"2026-07-29T11:27:00Z",enrichment_status:"complete",coverage:{},data_quality:{},views:{mon_sun:{totals:{eligible_ticket_count:10},outcomes:{},ai_first:{count:9,rate:.9},reopen:{},weekly:[week(10)],segments:{},rule_gt4:{}},mon_fri:{totals:{eligible_ticket_count:7},outcomes:{},ai_first:{count:6,rate:.86},reopen:{},weekly:[week(7)],segments:{},rule_gt4:{}}}}});
globalThis.__test.setWeekDefinition("mon_fri");
process.stdout.write(JSON.stringify({title:document.getElementById("dynamicTitle").textContent, rows:document.getElementById("weeklyRows").textContent}));
""")
    assert "T2–T6" in observed["title"]
    assert "7" in observed["rows"]


def test_all_five_narrative_templates_and_tie_safe_transfer_reason():
    observed = run(page_text(), r"""
const view={totals:{eligible_ticket_count:20,transfer_total:4},ai_first:{count:16,rate:.8},reopen:{lifetime:{numerator:4,denominator:20}},rule_gt4:{gt4_turn_without_cs:2},weekly:[{total_tickets:20,ai_first_rate:.8,reopen_lifetime_rate:.2,gt4_turn_without_cs:1},{total_tickets:19,ai_first_rate:.75,reopen_lifetime_rate:.205,gt4_turn_without_cs:2}],transfer_reasons:{observed_transfer_denominator:4,guardrail:[{rule:"missing_transaction_id",count:4}]}};
globalThis.__test.renderNarrative(view,{enrichment_status:"partial"}); const first=document.getElementById("narrativeSummary").textContent;
view.transfer_reasons.guardrail=[{rule:"a",count:4},{rule:"b",count:4}]; globalThis.__test.renderNarrative(view,{enrichment_status:"complete"});
process.stdout.write(JSON.stringify({first,tied:document.getElementById("narrativeSummary").textContent}));
""")
    for phrase in ("AI First", "Reopen sau AI First", "Chuyển CS nhiều nhất", "quá 4 turn", "Thiếu dữ liệu bổ sung"):
        assert phrase in observed["first"]
    assert "Chuyển CS nhiều nhất" not in observed["tied"]
    assert '"a"' not in observed["tied"]


def test_guardrail_panel_explains_overlapping_rule_counts_without_tie_breaking():
    page = page_text()
    assert "Một ticket có thể kích hoạt nhiều rule" in page


def test_reopen_reason_legacy_payload_and_pending_status_show_no_fake_zero_metric():
    observed = run(page_text(), r"""
const legacy={weekly:[{cohort_week:"2026-07-20",has_data:true,total_tickets:10}]};
globalThis.__test.renderReopenReason(legacy);
const missing=document.getElementById("reopenReasonStatus").textContent;
globalThis.__test.renderReopenReason({weekly:[{cohort_week:"2026-07-20",has_data:true,total_tickets:10,reopen_reason:{status:"pending"}}]});
const pending=document.getElementById("reopenReasonStatus").textContent;
process.stdout.write(JSON.stringify({missing,pending}));
""")
    expected = "Đang chờ taxonomy/đánh giá; chưa có nhãn do model gợi ý."
    assert expected in observed["missing"]
    assert expected in observed["pending"]
    assert "0%" not in observed["missing"]
    assert "0%" not in observed["pending"]


def test_reopen_reason_unavailable_keeps_deterministic_dashboard_message_explicit():
    observed = run(page_text(), r"""
globalThis.__test.renderReopenReason({weekly:[{cohort_week:"2026-07-20",has_data:true,total_tickets:10,reopen_reason:{status:"unavailable"}}]});
process.stdout.write(JSON.stringify({text:document.getElementById("reopenReasonStatus").textContent}));
""")
    assert "Lớp gợi ý không khả dụng" in observed["text"]
    assert "metric deterministic vẫn cập nhật" in observed["text"]
    assert "0%" not in observed["text"]


def test_reopen_reason_labeled_uses_active_week_and_ignores_private_evidence_fields():
    observed = run(page_text(), r"""
globalThis.fetch=async()=>({ok:true,json:async()=>({items:[],page:1,page_size:50,total:0})});
const pending={cohort_week:"2026-07-13",has_data:true,total_tickets:10,reopen_reason:{status:"pending"}};
const labeled={cohort_week:"2026-07-20",has_data:true,total_tickets:12,reopen_reason:{
 status:"labeled",labels_version:"v1",
 counts:{ai_wrong_content:{ai_end_to_end:2,ai_then_cs:1},other:{ai_end_to_end:1,ai_then_cs:0}},
 by_business:{"Thanh toán-IBFT":{ai_wrong_content:3,other:1}},
 coverage:{population:5,labeled:4,abstained:1,failed:1,invalid:0},
 control:{direct_cs_reopen_7d_rate:.25,direct_cs_denominator:8},
 session_id:"private-session",trace_id:"private-trace",quote:"private quote",evidence:"private evidence"
}};
const view={totals:{eligible_ticket_count:22},ai_first:{},reopen:{lifetime:{}},weekly:[pending,labeled],segments:{},rule_gt4:{}};
globalThis.__test.applyEnvelope({status:"ready",snapshot:{generated_at:"2026-07-29T01:00:00Z",coverage:{},data_quality:{},views:{mon_sun:view,mon_fri:view}}});
globalThis.__test.setWeekFilter("2026-07-13");
const before=document.getElementById("reopenReasonStatus").textContent;
globalThis.__test.setWeekFilter("2026-07-20");
const ids=["reopenReasonStatus","reopenReasonCoverage","reopenReasonControl","reopenReasonCounts","reopenReasonBusiness"];
const text=ids.map(id=>document.getElementById(id).textContent).join(" ");
const tags=["reopenReasonCounts","reopenReasonBusiness"].flatMap(id=>document.getElementById(id).children.map(node=>node.tagName));
process.stdout.write(JSON.stringify({before,text,tags}));
""")
    assert "Đang chờ taxonomy/đánh giá" in observed["before"]
    assert "Nhãn do model gợi ý" in observed["text"]
    assert "4 / 5 ticket" in observed["text"]
    assert "25,0%" in observed["text"] and "8 ticket" in observed["text"]
    assert "ai_wrong_content" in observed["text"]
    assert "Thanh toán-IBFT" in observed["text"]
    for forbidden in ("private-session", "private-trace", "private quote", "private evidence"):
        assert forbidden not in observed["text"]
    assert "svg" not in observed["tags"]


def test_reopen_reason_tracks_the_active_week_definition_view():
    observed = run(page_text(), r"""
globalThis.fetch=async()=>({ok:true,json:async()=>({items:[],page:1,page_size:50,total:0})});
const week=(status)=>({cohort_week:"2026-07-20",has_data:true,total_tickets:10,reopen_reason:{status}});
const base={totals:{eligible_ticket_count:10},ai_first:{},reopen:{lifetime:{}},segments:{},rule_gt4:{}};
globalThis.__test.applyEnvelope({status:"ready",snapshot:{generated_at:"2026-07-29T01:00:00Z",coverage:{},data_quality:{},views:{
 mon_sun:{...base,weekly:[week("pending")]},
 mon_fri:{...base,weekly:[week("unavailable")]}
}}});
const monSun=document.getElementById("reopenReasonStatus").textContent;
globalThis.__test.setWeekDefinition("mon_fri");
const monFri=document.getElementById("reopenReasonStatus").textContent;
process.stdout.write(JSON.stringify({monSun,monFri}));
""")
    assert "Đang chờ taxonomy/đánh giá" in observed["monSun"]
    assert "Lớp gợi ý không khả dụng" in observed["monFri"]


def test_narrative_never_compares_wtd_to_a_completed_week():
    observed = run(page_text(), r"""
const view={totals:{eligible_ticket_count:20,transfer_total:0},ai_first:{count:16,rate:.8},reopen:{lifetime:{numerator:4,denominator:20}},rule_gt4:{},weekly:[
 {cohort_week:"2026-07-06",cohort_status:"complete",has_data:false,total_tickets:0},
 {cohort_week:"2026-07-13",cohort_status:"complete",has_data:true,total_tickets:20,ai_first_rate:.7,reopen_lifetime_rate:.2},
 {cohort_week:"2026-07-20",cohort_status:"wtd",has_data:true,total_tickets:5,ai_first_rate:.9,reopen_lifetime_rate:.4}
]};
globalThis.__test.renderNarrative(view,{enrichment_status:"complete"});
process.stdout.write(JSON.stringify({text:document.getElementById("narrativeSummary").textContent}));
""")
    assert observed["text"].count("chưa có tuần trước để so sánh") == 2


def test_weekly_copy_and_csv_export_have_14_columns_and_utf8_bom():
    observed = run(page_text(), r"""
const week={cohort_week:"2026-07-20",cohort_status:"wtd",has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:.8,ai_end_to_end_count:6,ai_then_cs_count:2,direct_cs_count:1,unclassified_count:1,reopen_lifetime_numerator:2,reopen_lifetime_rate:.25,ai_reply_mean_ai_first:1.2,gt4_turn_with_cs:1,gt4_turn_without_cs:2};
const value=globalThis.__test.buildWeeklyExport([week],"T2–CN","2026-07-29 18:27");
process.stdout.write(JSON.stringify(value));
""")
    assert observed["tsv"].splitlines()[0].startswith("# Cohort: T2–CN")
    assert len(observed["tsv"].splitlines()[1].split("\t")) == 14
    assert observed["csv"].startswith("\ufeff# Cohort: T2–CN")


def test_segment_scope_keeps_dashboard_headline_truthful_and_labels_explorer_filter():
    observed = run(page_text(), r"""
globalThis.fetch=async()=>({ok:true,json:async()=>({items:[],page:1,page_size:50,total:0})});
const week=(index)=>({cohort_week:`2026-0${index < 9 ? 1 : 2}-${String(index + 1).padStart(2,"0")}`,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:.8,ai_end_to_end_count:7,ai_then_cs_count:1,direct_cs_count:1,unclassified_count:1,reopen_lifetime_numerator:1,reopen_lifetime_rate:.1,ai_reply_mean_ai_first:1,gt4_turn_with_cs:0,gt4_turn_without_cs:0});
const weekly=Array.from({length:13},(_,index)=>week(index));
const view={totals:{eligible_ticket_count:130},ai_first:{count:104,rate:.8},reopen:{lifetime:{numerator:13,denominator:130}},weekly,segments:{issue_category:{"Thanh toán":{total:11,ai_first:9,transferred:2,reopen:1}}},rule_gt4:{}};
globalThis.__test.applyEnvelope({status:"ready",snapshot:{generated_at:"2026-07-29T01:00:00Z",coverage:{},data_quality:{},views:{mon_sun:view,mon_fri:view}}});
globalThis.__test.setSegmentFilter("issue_category","Thanh toán");
process.stdout.write(JSON.stringify({title:document.getElementById("dynamicTitle").textContent,chip:document.getElementById("activeFilterChips").textContent}));
""")
    assert observed == {
        "title": "Toàn kỳ · cohort T2–CN · 13 tuần · 130 ticket",
        "chip": "Ticket Explorer · Nhóm vấn đề: Thanh toán×",
    }


def test_reopen_warning_marks_only_completed_week_increase_above_five_points():
    observed = run(page_text(), r"""
globalThis.fetch=async()=>({ok:true,json:async()=>({items:[],page:1,page_size:50,total:0})});
const week=(date,reopen)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:.8,ai_end_to_end_count:7,ai_then_cs_count:1,direct_cs_count:1,unclassified_count:1,reopen_lifetime_numerator:1,reopen_lifetime_rate:reopen,ai_reply_mean_ai_first:1,gt4_turn_with_cs:0,gt4_turn_without_cs:0});
const view={totals:{eligible_ticket_count:20},ai_first:{count:16,rate:.8},reopen:{lifetime:{numerator:3,denominator:20}},weekly:[week("2026-07-13",.10),week("2026-07-20",.17)],segments:{},rule_gt4:{}};
globalThis.__test.applyEnvelope({status:"ready",snapshot:{generated_at:"2026-07-29T01:00:00Z",coverage:{},data_quality:{},views:{mon_sun:view,mon_fri:view}}});
const card=document.getElementById("kpiGrid").children[2];
process.stdout.write(JSON.stringify({attention:card.classList.contains("attention"),text:card.textContent,title:card.getAttribute("title")}));
""")
    assert observed["attention"] is True
    assert "Tăng trên 5 điểm" in observed["text"]
    assert "Cập nhật" in observed["text"]
    assert observed["title"] == "Tỷ lệ ticket AI First có reopen lifetime; chỉ so sánh các tuần đã hoàn tất."


def test_reopen_warning_uses_display_rounded_threshold_and_complete_values_only():
    observed = run(page_text(), r"""
globalThis.fetch=async()=>({ok:true,json:async()=>({items:[],page:1,page_size:50,total:0})});
const week=(date,reopen,status="complete")=>({cohort_week:date,cohort_status:status,has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:.8,ai_end_to_end_count:7,ai_then_cs_count:1,direct_cs_count:1,unclassified_count:1,reopen_lifetime_numerator:reopen==null?0:1,reopen_lifetime_rate:reopen,ai_reply_mean_ai_first:1,gt4_turn_with_cs:0,gt4_turn_without_cs:0});
const view=(prior,current,status="complete")=>({totals:{eligible_ticket_count:20},ai_first:{count:16,rate:.8},reopen:{lifetime:{numerator:2,denominator:20}},weekly:[week("2026-07-13",prior),week("2026-07-20",current,status)],segments:{},rule_gt4:{}});
const inspect=(prior,current,status="complete")=>{globalThis.__test.renderKpis(view(prior,current,status));const card=document.getElementById("kpiGrid").children[2];return {attention:card.classList.contains("attention"),warning:card.textContent.includes("Tăng trên 5 điểm")}};
const exact=inspect(.15,.20);
const above=inspect(.15,.201);
const decline=inspect(.20,.10);
const missingCurrent=inspect(.15,null);
const missingPrior=inspect(null,.20);
const wtdView=view(.15,.30,"wtd");
globalThis.__test.setSnapshot({views:{mon_sun:wtdView}});
globalThis.__test.setWeekFilter("2026-07-20");
const wtdCard=document.getElementById("kpiGrid").children[2];
const selectedWtd={attention:wtdCard.classList.contains("attention"),warning:wtdCard.textContent.includes("Tăng trên 5 điểm")};
process.stdout.write(JSON.stringify({exact,above,decline,selectedWtd,missingCurrent,missingPrior}));
""")
    assert observed == {
        "exact": {"attention": False, "warning": False},
        "above": {"attention": True, "warning": True},
        "decline": {"attention": False, "warning": False},
        "selectedWtd": {"attention": False, "warning": False},
        "missingCurrent": {"attention": False, "warning": False},
        "missingPrior": {"attention": False, "warning": False},
    }


def test_kpi_definitions_are_revealed_by_keyboard_focus_and_touch_activation():
    observed = run(page_text(), r"""
const selected={cohort_week:"2026-07-20",cohort_status:"complete",has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:.8,ai_end_to_end_count:7,ai_then_cs_count:1,direct_cs_count:1,unclassified_count:1,reopen_lifetime_numerator:1,reopen_lifetime_rate:.2,ai_reply_mean_ai_first:1,gt4_turn_with_cs:0,gt4_turn_without_cs:0};
const view={totals:{eligible_ticket_count:10},ai_first:{count:8,rate:.8},reopen:{lifetime:{numerator:1,denominator:10}},weekly:[selected],segments:{},rule_gt4:{}};
globalThis.__test.setSnapshot({generated_at:"2026-07-29T01:00:00Z",views:{mon_sun:view}});
const pairs=()=>document.getElementById("kpiGrid").children.map(card=>{const control=card.children.find(node=>node.tagName==="button"),describedBy=control&&control.getAttribute("aria-describedby"),description=card.children.find(node=>node.getAttribute("id")===describedBy);return {card,control,description}});
globalThis.__test.renderKpis(view);
const initial=pairs().map(({card,control,description})=>({controlText:control&&control.textContent,relation:Boolean(description)&&card.getAttribute("aria-describedby")===description.getAttribute("id")&&control.getAttribute("aria-describedby")===description.getAttribute("id"),expanded:control&&control.getAttribute("aria-expanded"),hidden:description&&description.hidden,title:card.getAttribute("title"),definition:description&&description.textContent}));
const keyboard=pairs().map(({control,description})=>{control.focus();return !description.hidden&&control.getAttribute("aria-expanded")==="true"});
globalThis.__test.renderKpis(view);
const touch=pairs().map(({control,description})=>{control.click();return !description.hidden&&control.getAttribute("aria-expanded")==="true"});
process.stdout.write(JSON.stringify({initial,keyboard,touch}));
""")
    definitions = [
        "Tỷ lệ ticket có phản hồi AI thực chất: AI xử lý trọn cộng AI trả lời rồi chuyển CS.",
        "Số ticket đủ điều kiện trong phạm vi đang hiển thị, không tính direct chat.",
        "Tỷ lệ ticket AI First có reopen lifetime; chỉ so sánh các tuần đã hoàn tất.",
        "Số ticket quá 4 turn nhưng chưa chuyển CS; cần xử lý.",
    ]
    assert [item["definition"] for item in observed["initial"]] == definitions
    assert [item["title"] for item in observed["initial"]] == definitions
    assert all(item["controlText"] == "Định nghĩa" for item in observed["initial"])
    assert all(item["relation"] for item in observed["initial"])
    assert all(item["expanded"] == "false" and item["hidden"] for item in observed["initial"])
    assert observed["keyboard"] == [True, True, True, True]
    assert observed["touch"] == [True, True, True, True]


def test_weekly_column_definitions_use_one_focusable_disclosure_with_all_fourteen_items():
    page = page_text()
    parser = Parser(); parser.feed(page)
    toggle = next(attrs for tag, attrs in parser.tags if tag == "button" and attrs.get("id") == "weeklyDefinitionsToggle")
    panel = next(attrs for tag, attrs in parser.tags if attrs.get("id") == "weeklyDefinitionsPanel")
    assert toggle.get("aria-controls") == "weeklyDefinitionsPanel"
    assert toggle.get("aria-expanded") == "false"
    assert panel.get("role") == "region"
    assert panel.get("aria-labelledby") == "weeklyDefinitionsToggle"
    assert "hidden" in panel

    observed = run(page, r"""
globalThis.fetch=async()=>({ok:true,json:async()=>({status:"ready",snapshot:null,items:[],page:1,page_size:50,total:0})});
document.dispatchEvent({type:"DOMContentLoaded"});
const toggle=document.getElementById("weeklyDefinitionsToggle"),panel=document.getElementById("weeklyDefinitionsPanel");
const initial={hidden:panel.hidden,expanded:toggle.getAttribute("aria-expanded")};
toggle.focus();toggle.click();
const open={hidden:panel.hidden,expanded:toggle.getAttribute("aria-expanded"),focused:document.activeElement===toggle,terms:panel.children.filter(node=>node.tagName==="dt").map(node=>node.textContent),definitions:panel.children.filter(node=>node.tagName==="dd").map(node=>node.textContent)};
toggle.click();
const closed={hidden:panel.hidden,expanded:toggle.getAttribute("aria-expanded"),focused:document.activeElement===toggle};
process.stdout.write(JSON.stringify({initial,open,closed}));
""")
    assert observed["initial"] == {"hidden": True, "expanded": "false"}
    assert observed["open"]["hidden"] is False
    assert observed["open"]["expanded"] == "true"
    assert observed["open"]["focused"] is True
    assert observed["open"]["terms"] == [
        "Tuần", "Tổng ticket", "AI First", "Tỷ lệ AI First", "AI xử lý trọn",
        "AI trả lời rồi chuyển CS", "Chuyển CS ngay từ đầu", "Tổng chuyển CS",
        "Reopen sau AI First", "Tỷ lệ reopen", "AI phản hồi/ticket TB", ">4 turn + CS",
        ">4 turn không CS", "Chưa phân loại",
    ]
    assert observed["open"]["definitions"] == [
        "Tuần cohort, neo thứ Hai; chọn T2–CN hoặc T2–T6.",
        "Số ticket đủ điều kiện, không tính direct chat.",
        "AI xử lý trọn cộng AI trả lời rồi chuyển CS.",
        "AI First chia tổng ticket.",
        "AI kết thúc ticket mà không chuyển CS.",
        "AI có trả lời trước khi chuyển CS.",
        "CS nhận ticket ngay, không có phản hồi AI thực chất trước đó.",
        "AI trả lời rồi chuyển CS cộng Chuyển CS ngay từ đầu.",
        "Số ticket AI First có reopen lifetime.",
        "Reopen lifetime chia ticket AI First; chỉ hiện khi cohort đủ 7 ngày.",
        "Số phản hồi AI trung bình trên ticket AI First.",
        "Ticket quá 4 turn đã chuyển CS.",
        "Ticket quá 4 turn chưa chuyển CS; cần xử lý.",
        "Ticket không đủ tín hiệu để phân loại outcome.",
    ]
    assert observed["closed"] == {"hidden": True, "expanded": "false", "focused": True}


def test_weekly_export_keeps_fourteen_columns_for_each_complete_data_row():
    observed = run(page_text(), r"""
const week=(date)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:.8,ai_end_to_end_count:6,ai_then_cs_count:2,direct_cs_count:1,unclassified_count:1,reopen_lifetime_numerator:2,reopen_lifetime_rate:.25,ai_reply_mean_ai_first:1.2,gt4_turn_with_cs:1,gt4_turn_without_cs:2});
const value=globalThis.__test.buildWeeklyExport([week("2026-07-13"),week("2026-07-20")],"T2–CN","2026-07-29 18:27");
const rows=value.tsv.split("\n");
process.stdout.write(JSON.stringify({headers:rows[1].split("\t"),columns:rows.slice(2).map(row=>row.split("\t").length)}));
""")
    assert observed["headers"] == [
        "Tuần", "Tổng ticket", "AI First", "Tỷ lệ AI First", "AI xử lý trọn",
        "AI trả lời rồi chuyển CS", "Chuyển CS ngay từ đầu", "Tổng chuyển CS",
        "Reopen sau AI First", "Tỷ lệ reopen", "AI phản hồi/ticket TB", ">4 turn + CS",
        ">4 turn không CS", "Chưa phân loại",
    ]
    assert observed["columns"] == [14, 14]
    parser = Parser(); parser.feed(page_text())
    weekly_headers = [attrs for tag, attrs in parser.tags if tag == "th" and attrs.get("scope") == "col"][:14]
    assert len(weekly_headers) == 14
    assert all(attrs.get("title") for attrs in weekly_headers)


def test_weekly_total_transfer_uses_schema_count_fields():
    observed = run(page_text(), r"""
const week={cohort_week:"2026-07-20",cohort_status:"complete",has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:.8,ai_end_to_end_count:6,ai_then_cs_count:2,direct_cs_count:1,unclassified_count:1,reopen_lifetime_numerator:2,reopen_lifetime_rate:.25,ai_reply_mean_ai_first:1.2,gt4_turn_with_cs:1,gt4_turn_without_cs:2};
process.stdout.write(JSON.stringify(globalThis.__test.weeklyValues(week)));
""")
    assert observed[5] == "2"
    assert observed[6] == "1"
    assert observed[7] == "3"


def test_mon_fri_date_range_ends_on_friday():
    observed = run(page_text(), r"""
globalThis.__test.setWeekDefinition("mon_fri");
process.stdout.write(JSON.stringify({range:globalThis.__test.dateRange("2026-07-20")}));
""")
    assert observed["range"] == "20/07 – 24/07"


def test_weekly_renderer_keeps_wtd_and_no_data_as_text_not_zeroes():
    observed = run(page_text(), r"""
globalThis.__test.renderWeeklyTable([
 {cohort_week:"2026-07-13",cohort_status:"complete",has_data:false,total_tickets:0},
 {cohort_week:"2026-07-20",cohort_status:"wtd",has_data:true,total_tickets:2,ai_first_count:1,ai_first_rate:.5,ai_end_to_end_count:1,ai_then_cs_count:0,direct_cs_count:1,unclassified_count:0,reopen_lifetime_numerator:0,reopen_lifetime_rate:null,ai_reply_mean_ai_first:1,gt4_turn_with_cs:0,gt4_turn_without_cs:0}
]);process.stdout.write(JSON.stringify({text:document.getElementById("weeklyRows").textContent}));
""")
    assert "Không có dữ liệu" in observed["text"]
    assert "WTD — chưa đủ tuần" in observed["text"]


def test_weekly_table_collapses_a_run_of_empty_weeks_into_one_row():
    """Bảng tuần từng mở đầu bằng 8 dòng 'Không có dữ liệu' trước dữ liệu thật."""
    observed = run(page_text(), r"""
const empty=(date)=>({cohort_week:date,has_data:false,total_tickets:0});
const full=(date)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:.8,ai_end_to_end_count:5,ai_then_cs_count:3,direct_cs_count:2,reopen_lifetime_numerator:1,reopen_lifetime_rate:.1,ai_reply_mean_ai_first:1.5,gt4_turn_with_cs:0,gt4_turn_without_cs:0,unclassified_count:0});
const weekly=[empty("2026-05-04"),empty("2026-05-11"),empty("2026-05-18"),full("2026-05-25"),full("2026-06-01")];
globalThis.__test.renderWeeklyTable(weekly);
const body=document.getElementById("weeklyRows");
const collapsed=body.children.map(row=>row.className);
const toggle=body.children.find(row=>row.className.includes("empty-group")).children[0].children[0];
const collapsedText=toggle.textContent;
toggle.dispatchEvent({type:"click"});
const expanded=document.getElementById("weeklyRows").children.map(row=>row.className);
process.stdout.write(JSON.stringify({collapsed,collapsedText,expanded}));
""")
    assert len(observed["collapsed"]) == 3, "3 tuần rỗng + 2 tuần dữ liệu -> 1 dòng gộp + 2 dòng"
    assert observed["collapsed"][0] == "empty-row empty-group"
    assert "3 tuần không có dữ liệu" in observed["collapsedText"]
    assert "04/05" in observed["collapsedText"]
    assert len(observed["expanded"]) == 5, "mở ra thì hiện đủ 5 dòng"


def test_weekly_table_keeps_an_interior_empty_week_in_place():
    """Tuần rỗng nằm giữa dữ liệu không được gộp lên đầu — thứ tự thời gian là thông tin."""
    observed = run(page_text(), r"""
const empty=(date)=>({cohort_week:date,has_data:false,total_tickets:0});
const full=(date)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:.8,ai_end_to_end_count:5,ai_then_cs_count:3,direct_cs_count:2,reopen_lifetime_numerator:1,reopen_lifetime_rate:.1,ai_reply_mean_ai_first:1.5,gt4_turn_with_cs:0,gt4_turn_without_cs:0,unclassified_count:0});
globalThis.__test.renderWeeklyTable([full("2026-06-01"),empty("2026-06-08"),full("2026-06-15")]);
const rows=document.getElementById("weeklyRows").children;
process.stdout.write(JSON.stringify({classes:rows.map(row=>row.className),second:rows[1].textContent}));
""")
    assert observed["classes"] == ["", "empty-row", ""], "cụm một tuần thì không gộp"
    assert "Không có dữ liệu" in observed["second"]


def test_immature_reopen_cell_explains_why_rate_is_missing():
    observed = run(page_text(), r"""
globalThis.__test.renderWeeklyTable([{cohort_week:"2026-07-20",cohort_status:"wtd",has_data:true,total_tickets:2,ai_first_count:1,ai_first_rate:.5,ai_end_to_end_count:1,ai_then_cs_count:0,direct_cs_count:1,unclassified_count:0,reopen_lifetime_numerator:0,reopen_lifetime_rate:null,ai_reply_mean_ai_first:1,gt4_turn_with_cs:0,gt4_turn_without_cs:0}]);
const cell=document.getElementById("weeklyRows").children[0].children[9];
process.stdout.write(JSON.stringify({text:cell.textContent,title:cell.getAttribute("title")}));
""")
    assert observed == {"text": "—", "title": "Cần 7 ngày sau tuần cohort"}


def test_transfer_reason_contract_uses_rule_tpe_object_and_snapshot_unmapped_codes():
    observed = run(page_text(), r"""
globalThis.__test.applyEnvelope({status:"ready",snapshot:{generated_at:"2026-07-29T01:00:00Z",coverage:{},data_quality:{},unmapped_tpe_codes:[{code:"-217",count:3}],views:{mon_sun:{totals:{},ai_first:{},reopen:{lifetime:{}},weekly:[],segments:{},rule_gt4:{},transfer_reasons:{observed_transfer_denominator:7,tpe:[{code:"-383",status:"Đang xử lý",case:2,count:4}],guardrail:[{rule:"off_topic",count:2}],escalation_guard_blocked:{count:1}}},mon_fri:{totals:{},ai_first:{},reopen:{lifetime:{}},weekly:[],segments:{},rule_gt4:{}}}}});
setImmediate(()=>process.stdout.write(JSON.stringify({tpe:document.getElementById("tpeDistribution").textContent,guardrail:document.getElementById("guardrailDistribution").textContent,escalation:document.getElementById("escalationPanel").textContent,unmapped:document.getElementById("unmappedTpePanel").textContent})));
""")
    assert "-383 · Đang xử lý · case 2" in observed["tpe"]
    assert "off_topic" in observed["guardrail"]
    assert "Mẫu số ticket đã chuyển CS: 7" in observed["guardrail"]
    assert "Ticket đã ở CS" in observed["escalation"]
    assert "-217" in observed["unmapped"]


def test_dq_score_uses_spec_weighted_formula_not_a_coverage_average():
    observed = run(page_text(), r"""
Date.now=()=>1000;globalThis.__test.renderQuality({generated_at:"1970-01-01T00:00:01Z",coverage:{issue_category:.5,tpe:.5,skill:.5},gate_status:{structural_invalid_rate:.5},data_quality:{}});process.stdout.write(JSON.stringify({score:document.getElementById("dqScoreValue").textContent,bullet:document.getElementById("dqBullet").value,badge:document.getElementById("dqBadge").className}));
""")
    assert observed["score"] == "55%"
    assert observed["bullet"] == 55
    assert "dq-bad" in observed["badge"]


def test_new_snapshot_generation_resets_ticket_pagination_to_one():
    observed = run(page_text(), r"""
const requests=[];globalThis.fetch=async(url)=>{requests.push(url);return {ok:true,json:async()=>({items:[],page:1,page_size:50,total:0})}};
const view={totals:{eligible_ticket_count:0},outcomes:{},ai_first:{count:0,rate:0},reopen:{lifetime:{numerator:0,denominator:0}},weekly:[],segments:{},rule_gt4:{}};
globalThis.__test.applyEnvelope({status:"ready",snapshot:{generated_at:"2026-07-29T01:00:00Z",coverage:{},data_quality:{},views:{mon_sun:view,mon_fri:view}}});
globalThis.__test.setTicketPage(9);
globalThis.__test.applyEnvelope({status:"ready",snapshot:{generated_at:"2026-07-29T02:00:00Z",coverage:{},data_quality:{},views:{mon_sun:view,mon_fri:view}}});
setImmediate(()=>process.stdout.write(JSON.stringify({page:globalThis.__test.getTicketPage(),requests})));
""")
    assert observed["page"] == 1


def test_week_filter_updates_rule_panel_reasons_explorer_and_visible_chip():
    observed = run(page_text(), r"""
const requests=[];globalThis.fetch=async(url)=>{requests.push(url);return {ok:true,json:async()=>({items:[],page:1,page_size:50,total:0})}};
const week=(date,gt4)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_count:6,ai_first_rate:.6,ai_end_to_end_count:4,ai_then_cs_count:2,direct_cs_count:1,unclassified_count:3,reopen_lifetime_numerator:1,reopen_lifetime_rate:.1,ai_reply_mean_ai_first:1,gt4_turn_with_cs:gt4,gt4_turn_without_cs:gt4+1,max_replies_rule_fired:gt4+2});
const view={totals:{eligible_ticket_count:20,transfer_total:3},ai_first:{count:12,rate:.6},reopen:{lifetime:{numerator:2,denominator:20}},weekly:[week("2026-07-13",1),week("2026-07-20",5)],segments:{issue_category:{}},rule_gt4:{gt4_turn_total:99,gt4_turn_with_cs:98,gt4_turn_without_cs:97,max_replies_rule_fired:96},transfer_reasons:{guardrail:[]},by_week:{"2026-07-20":{transfer_reasons:{tpe:[],guardrail:[{rule:"off_topic",count:2}],escalation_guard_blocked:{count:1}}}}};
globalThis.__test.applyEnvelope({status:"ready",snapshot:{generated_at:"2026-07-29T01:00:00Z",coverage:{},data_quality:{},views:{mon_sun:view,mon_fri:view}}});globalThis.__test.setWeekFilter("2026-07-20");setImmediate(()=>process.stdout.write(JSON.stringify({rule:document.getElementById("ruleGt4Panel").textContent,reason:document.getElementById("guardrailDistribution").textContent,chips:document.getElementById("activeFilterChips").textContent,requests})));
""")
    assert "6" in observed["rule"] and "7" in observed["rule"]
    assert "off_topic" in observed["reason"]
    assert "Tuần 20/07" in observed["chips"]
    assert any("cohort_week=2026-07-20" in request for request in observed["requests"])


def test_week_filter_updates_kpis_and_segment_buckets_not_only_diagnostics():
    observed = run(page_text(), r"""
globalThis.fetch=async()=>({ok:true,json:async()=>({items:[],page:1,page_size:50,total:0})});
const week=(date,total,ai)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:total,ai_first_count:ai,ai_first_rate:ai/total,ai_end_to_end_count:ai-1,ai_then_cs_count:1,direct_cs_count:1,unclassified_count:total-ai-1,reopen_lifetime_numerator:1,reopen_lifetime_rate:.1,ai_reply_mean_ai_first:1,gt4_turn_with_cs:0,gt4_turn_without_cs:0,max_replies_rule_fired:0});
const view={totals:{eligible_ticket_count:30,transfer_total:3},ai_first:{count:20,rate:.667},reopen:{lifetime:{numerator:3,denominator:30}},weekly:[week("2026-07-13",20,10),week("2026-07-20",10,8)],segments:{issue_category:{all_time:{total:30,ai_first:20,transferred:3,reopen:3}}},rule_gt4:{},transfer_reasons:{observed_transfer_denominator:3,tpe:[],guardrail:[],escalation_guard_blocked:{count:0}},by_week:{"2026-07-20":{segments:{issue_category:{selected_week:{total:10,ai_first:8,transferred:2,reopen:1}}},transfer_reasons:{observed_transfer_denominator:2,tpe:[],guardrail:[],escalation_guard_blocked:{count:0}}}}};
globalThis.__test.applyEnvelope({status:"ready",snapshot:{generated_at:"2026-07-29T01:00:00Z",coverage:{},data_quality:{},views:{mon_sun:view,mon_fri:view}}});
globalThis.__test.setWeekFilter("2026-07-20");
setImmediate(()=>process.stdout.write(JSON.stringify({kpis:document.getElementById("kpiGrid").textContent,segments:document.getElementById("segmentList").textContent})));
""")
    assert "80,0%" in observed["kpis"]
    assert "10" in observed["kpis"]
    assert "selected_week" in observed["segments"]
    assert "all_time" not in observed["segments"]


def test_week_filter_drives_narrative_reason_and_stuck_count():
    observed = run(page_text(), r"""
globalThis.fetch=async()=>({ok:true,json:async()=>({items:[],page:1,page_size:50,total:0})});
const week={cohort_week:"2026-07-20",cohort_status:"complete",has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:.8,ai_end_to_end_count:7,ai_then_cs_count:1,direct_cs_count:1,unclassified_count:1,reopen_lifetime_numerator:1,reopen_lifetime_rate:.1,ai_reply_mean_ai_first:1,gt4_turn_with_cs:1,gt4_turn_without_cs:2,max_replies_rule_fired:3};
const view={totals:{eligible_ticket_count:10,transfer_total:0},ai_first:{count:8,rate:.8},reopen:{lifetime:{numerator:1,denominator:10}},weekly:[week],segments:{issue_category:{}},rule_gt4:{gt4_turn_without_cs:99},transfer_reasons:{observed_transfer_denominator:2,tpe:[],guardrail:[{rule:"all_period_rule",count:9}],escalation_guard_blocked:{count:0}},by_week:{"2026-07-20":{segments:{issue_category:{}},transfer_reasons:{observed_transfer_denominator:2,tpe:[],guardrail:[{rule:"week_rule",count:2}],escalation_guard_blocked:{count:0}}}}};
globalThis.__test.applyEnvelope({status:"ready",snapshot:{generated_at:"2026-07-29T01:00:00Z",enrichment_status:"complete",coverage:{},data_quality:{},views:{mon_sun:view,mon_fri:view}}});
globalThis.__test.setWeekFilter("2026-07-20");
setImmediate(()=>process.stdout.write(JSON.stringify({text:document.getElementById("narrativeSummary").textContent})));
""")
    assert "week_rule" in observed["text"]
    assert "all_period_rule" not in observed["text"]
    assert "2 ticket quá 4 turn" in observed["text"]
    assert "99 ticket" not in observed["text"]


def test_segment_tab_filter_and_top12_expansion_are_separate_and_show_transfer_rate():
    observed = run(page_text(), r"""
const source={};for(let i=0;i<13;i++)source["segment"+i]={total:13-i,ai_first:6,transferred:3};
globalThis.fetch=async()=>({ok:true,json:async()=>({items:[],page:1,page_size:50,total:0})});
globalThis.__test.applyEnvelope({status:"ready",snapshot:{generated_at:"2026-07-29T01:00:00Z",coverage:{},data_quality:{},views:{mon_sun:{totals:{},ai_first:{},reopen:{lifetime:{}},weekly:[],segments:{issue_category:source,app:{}},rule_gt4:{}},mon_fri:{totals:{},ai_first:{},reopen:{lifetime:{}},weekly:[],segments:{},rule_gt4:{}}}}});
globalThis.__test.setSegmentDimension("issue_category");globalThis.__test.setSegmentFilter("app","segment0");globalThis.__test.toggleSegmentExpansion();
process.stdout.write(JSON.stringify({list:document.getElementById("segmentList").textContent,chips:document.getElementById("activeFilterChips").textContent}));
""")
    assert "% chuyển CS" in observed["list"]
    assert "segment12" in observed["list"]
    assert "Ticket Explorer · App: segment0" in observed["chips"]


def test_segment_aggregate_tail_collapses_metrics_and_expands_without_duplicate():
    observed = run(page_text(), r"""
const source=Object.fromEntries(Array.from({length:14},(_,index)=>[`segment${index}`,{total:100-index,ai_first:10+index,transferred:2+index,reopen:index}]));
const view={segments:{issue_category:source}};
globalThis.__test.setSnapshot({views:{mon_sun:view}});
globalThis.__test.setSegmentDimension("issue_category");
globalThis.__test.renderSegments(view);
const collapsedRows=document.getElementById("segmentList").children.filter(node=>node.className==="rank-row");
const collapsedAggregate=collapsedRows.filter(row=>row.children[0].textContent==="Khác (2 mục)");
const collapsed=document.getElementById("segmentList").textContent;
globalThis.__test.toggleSegmentExpansion();
const expandedRows=document.getElementById("segmentList").children.filter(node=>node.className==="rank-row");
const expandedAggregate=expandedRows.filter(row=>row.children[0].textContent==="Khác (2 mục)");
const expanded=document.getElementById("segmentList").textContent;
process.stdout.write(JSON.stringify({collapsed,expanded,collapsedAggregate:collapsedAggregate.length,collapsedReopen:collapsedAggregate[0]&&collapsedAggregate[0].children[1].getAttribute("aria-label"),expandedAggregate:expandedAggregate.length}));
""")
    assert "Khác (2 mục)" in observed["collapsed"]
    assert "175 N" in observed["collapsed"]
    assert "25,7% AI · 16,6% chuyển CS" in observed["collapsed"]
    assert "segment12" not in observed["collapsed"]
    assert "segment13" not in observed["collapsed"]
    assert observed["collapsedAggregate"] == 1
    assert observed["collapsedReopen"] == "Khác (2 mục): 175 ticket · 25 reopen"
    assert all(f"segment{index}" in observed["expanded"] for index in range(14))
    assert "Khác (2 mục)175 N" not in observed["expanded"]
    assert observed["expandedAggregate"] == 0


def test_segment_expansion_static_control_retains_focus_through_expand_and_collapse():
    observed = run(page_text(), r"""
globalThis.fetch=async()=>({ok:true,json:async()=>({status:"ready",snapshot:null,items:[],page:1,page_size:50,total:0})});
document.dispatchEvent({type:"DOMContentLoaded"});
const source=Object.fromEntries(Array.from({length:14},(_,index)=>[`segment${index}`,{total:100-index,ai_first:10+index,transferred:2+index,reopen:index}]));
const view={segments:{issue_category:source}};
globalThis.__test.setSnapshot({views:{mon_sun:view}});
globalThis.__test.setSegmentDimension("issue_category");
const toggle=document.getElementById("segmentExpansionToggle"),list=document.getElementById("segmentList");
const initial={hidden:toggle.hidden,expanded:toggle.getAttribute("aria-expanded"),text:toggle.textContent,tail:list.textContent.includes("segment13")};
toggle.focus();toggle.click();
const open={focused:document.activeElement===toggle,hidden:toggle.hidden,expanded:toggle.getAttribute("aria-expanded"),text:toggle.textContent,tail:list.textContent.includes("segment13")};
toggle.click();
const closed={focused:document.activeElement===toggle,hidden:toggle.hidden,expanded:toggle.getAttribute("aria-expanded"),text:toggle.textContent,tail:list.textContent.includes("segment13")};
process.stdout.write(JSON.stringify({initial,open,closed}));
""")
    assert observed == {
        "initial": {"hidden": False, "expanded": "false", "text": "Xem 2 mục còn lại", "tail": False},
        "open": {"focused": True, "hidden": False, "expanded": "true", "text": "Thu gọn", "tail": True},
        "closed": {"focused": True, "hidden": False, "expanded": "false", "text": "Xem 2 mục còn lại", "tail": False},
    }


def test_diagnostic_scope_captions_follow_period_and_cohort():
    observed = run(page_text(), r"""
const view={rule_gt4:{gt4_turn_total:4,gt4_turn_with_cs:1,gt4_turn_without_cs:3,max_replies_rule_fired:2},transfer_reasons:{observed_transfer_denominator:2,tpe:[],guardrail:[],escalation_guard_blocked:{count:0}}};
globalThis.__test.renderTransferReasons(view);
globalThis.__test.renderRules(view);
process.stdout.write(JSON.stringify({transfer:document.getElementById("transferScope").textContent,rule:document.getElementById("ruleScope").textContent}));
""")
    assert observed == {
        "transfer": "Phạm vi: Toàn kỳ · cohort T2–CN.",
        "rule": "Phạm vi: Toàn kỳ · cohort T2–CN.",
    }


def test_refresh_clears_stale_week_before_diagnostic_panels_fall_back_to_all_period():
    observed = run(page_text(), r"""
globalThis.fetch=async()=>({ok:true,json:async()=>({items:[],page:1,page_size:50,total:0})});
const week={cohort_week:"2026-07-20",cohort_status:"complete",has_data:true,total_tickets:10,ai_first_count:8,ai_first_rate:.8,ai_end_to_end_count:7,ai_then_cs_count:1,direct_cs_count:1,unclassified_count:1,reopen_lifetime_numerator:1,reopen_lifetime_rate:.1,ai_reply_mean_ai_first:1,gt4_turn_with_cs:1,gt4_turn_without_cs:2,max_replies_rule_fired:3};
const selected={totals:{eligible_ticket_count:10},ai_first:{count:8,rate:.8},reopen:{lifetime:{numerator:1,denominator:10}},weekly:[week],segments:{},rule_gt4:{gt4_turn_total:3,gt4_turn_with_cs:1,gt4_turn_without_cs:2,max_replies_rule_fired:3},transfer_reasons:{observed_transfer_denominator:2,tpe:[],guardrail:[{rule:"all_period",count:2}]},by_week:{"2026-07-20":{transfer_reasons:{observed_transfer_denominator:1,tpe:[],guardrail:[{rule:"selected_week",count:1}]}}}};
const refreshed={totals:{eligible_ticket_count:9},ai_first:{count:7,rate:.778},reopen:{lifetime:{numerator:1,denominator:9}},weekly:[],segments:{},rule_gt4:{gt4_turn_total:9,gt4_turn_with_cs:4,gt4_turn_without_cs:5,max_replies_rule_fired:6},transfer_reasons:{observed_transfer_denominator:3,tpe:[],guardrail:[{rule:"all_period",count:3}]}};
globalThis.__test.applyEnvelope({status:"ready",snapshot:{generated_at:"2026-07-29T01:00:00Z",coverage:{},data_quality:{},views:{mon_sun:selected,mon_fri:selected}}});
globalThis.__test.setWeekFilter("2026-07-20");
globalThis.__test.applyEnvelope({status:"ready",snapshot:{generated_at:"2026-07-29T02:00:00Z",coverage:{},data_quality:{},views:{mon_sun:refreshed,mon_fri:refreshed}}});
process.stdout.write(JSON.stringify({transfer:document.getElementById("transferScope").textContent,rule:document.getElementById("ruleScope").textContent,query:Object.fromEntries(globalThis.__test.buildTicketQuery())}));
""")
    assert observed == {
        "transfer": "Phạm vi: Toàn kỳ · cohort T2–CN.",
        "rule": "Phạm vi: Toàn kỳ · cohort T2–CN.",
        "query": {"page": "1", "page_size": "50", "week_definition": "mon_sun"},
    }


def test_keyboard_segment_tabs_keep_selected_tab_tabindex_and_focus_aligned():
    observed = run(page_text(), r"""
const tabList=document.getElementById("segmentTabs");
const tabs=["issue_category","app","product_code","intent"].map((segment,index)=>{const tab=document.createElement("button");tab.dataset={segment};tab.setAttribute("aria-selected",String(index===0));tab.setAttribute("tabindex",index===0?"0":"-1");return tab});
tabList.append(...tabs);
document.dispatchEvent({type:"DOMContentLoaded"});
const press=(target,key)=>tabList.dispatchEvent({type:"keydown",target,key,preventDefault(){}});
press(tabs[0],"ArrowRight");
const afterRight={selected:tabs.map(tab=>tab.getAttribute("aria-selected")),tabindex:tabs.map(tab=>tab.getAttribute("tabindex")),focused:tabs.indexOf(document.activeElement)};
press(tabs[1],"End");
const afterEnd={selected:tabs.map(tab=>tab.getAttribute("aria-selected")),tabindex:tabs.map(tab=>tab.getAttribute("tabindex")),focused:tabs.indexOf(document.activeElement)};
press(tabs[3],"Home");
const afterHome={selected:tabs.map(tab=>tab.getAttribute("aria-selected")),tabindex:tabs.map(tab=>tab.getAttribute("tabindex")),focused:tabs.indexOf(document.activeElement)};
process.stdout.write(JSON.stringify({afterRight,afterEnd,afterHome}));
""")
    assert observed["afterRight"] == {"selected": ["false", "true", "false", "false"], "tabindex": ["-1", "0", "-1", "-1"], "focused": 1}
    assert observed["afterEnd"] == {"selected": ["false", "false", "false", "true"], "tabindex": ["-1", "-1", "-1", "0"], "focused": 3}
    assert observed["afterHome"] == {"selected": ["true", "false", "false", "false"], "tabindex": ["0", "-1", "-1", "-1"], "focused": 0}


def test_segment_tabpanel_accessible_name_tracks_initial_and_keyboard_selected_tab():
    page = page_text()
    parser = Parser(); parser.feed(page)
    tabs = [attrs for tag, attrs in parser.tags if tag == "button" and attrs.get("role") == "tab"]
    assert [tab.get("id") for tab in tabs] == [
        "segmentTabIssueCategory", "segmentTabApp", "segmentTabProductCode", "segmentTabIntent",
    ]
    panel = next(attrs for tag, attrs in parser.tags if attrs.get("id") == "segmentList")
    assert panel.get("role") == "tabpanel"
    assert panel.get("aria-labelledby") == "segmentTabIssueCategory"

    observed = run(page, r"""
const tabList=document.getElementById("segmentTabs"),panel=document.getElementById("segmentList");
const ids=["segmentTabIssueCategory","segmentTabApp","segmentTabProductCode","segmentTabIntent"];
const tabs=["issue_category","app","product_code","intent"].map((segment,index)=>{const tab=document.createElement("button");tab.dataset={segment};tab.setAttribute("id",ids[index]);tab.setAttribute("aria-selected",String(index===0));tab.setAttribute("tabindex",index===0?"0":"-1");return tab});
tabList.append(...tabs);
globalThis.fetch=async()=>({ok:true,json:async()=>({status:"ready",snapshot:null,items:[],page:1,page_size:50,total:0})});
document.dispatchEvent({type:"DOMContentLoaded"});
const initial=panel.getAttribute("aria-labelledby");
tabList.dispatchEvent({type:"keydown",target:tabs[0],key:"ArrowRight",preventDefault(){}});
process.stdout.write(JSON.stringify({initial,selected:panel.getAttribute("aria-labelledby"),focused:document.activeElement===tabs[1],states:tabs.map(tab=>tab.getAttribute("aria-selected"))}));
""")
    assert observed == {
        "initial": "segmentTabIssueCategory",
        "selected": "segmentTabApp",
        "focused": True,
        "states": ["false", "true", "false", "false"],
    }


def test_mobile_table_has_exactly_six_default_columns_and_quality_marks_stale_data():
    page = page_text()
    assert "const mobileColumns=new Set([0,1,3,7,9,12])" in page
    parser = Parser(); parser.feed(page)
    headers = [attrs for tag, attrs in parser.tags if tag == "th" and attrs.get("scope") == "col"]
    assert len([attrs for attrs in headers[:14] if "compact-hide" not in (attrs.get("class") or "")]) == 6
    observed = run(page, r"""
Date.now=()=>1000*60*16;globalThis.__test.renderQuality({generated_at:"1970-01-01T00:00:00Z",coverage:{issue_category:1,tpe:1,skill:.5},gate_status:{structural_invalid_rate:0},data_quality:{},data_range:{weeks_without_data:["2026-07-01"]},unmapped_tpe_codes:[{code:"-217",count:2}]});process.stdout.write(JSON.stringify({dq:document.getElementById("dqBadge").className,quality:document.getElementById("gateGrid").textContent}));
""")
    assert "dq-warn" in observed["dq"]
    assert "dữ liệu cũ" in observed["quality"]
    assert "-217" in observed["quality"]


def test_trend_places_first_data_week_at_the_left_edge_and_scales_to_render_box():
    """8 tuần rỗng đứng đầu từng đẩy 5 cột dữ liệu về 1/3 phải; preserveAspectRatio=none giãn ngang 4,3x."""
    page = page_text()
    assert 'preserveAspectRatio="none"' not in page
    assert 'preserveAspectRatio","xMidYMid meet"' in page

    observed = run(page, r"""
const empty=[4,11,18,25].map(day=>({cohort_week:`2026-05-${String(day).padStart(2,"0")}`,has_data:false,total_tickets:0}));
const full=(date)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_rate:.8,reopen_lifetime_rate:.2});
globalThis.__test.renderTrend([...empty,full("2026-06-01"),full("2026-06-08"),full("2026-06-15")]);
const bars=document.getElementById("trendChart").children.filter(node=>node.tagName==="rect");
process.stdout.write(JSON.stringify({count:bars.length,firstX:Number(bars[0].getAttribute("x")),lastX:Number(bars.at(-1).getAttribute("x"))}));
""")
    assert observed["count"] == 3, "chỉ vẽ tuần có dữ liệu"
    assert observed["firstX"] <= 32, "cột đầu phải ở 1/10 đầu của viewBox rộng 320"
    assert observed["lastX"] >= 280, "cột cuối phải gần mép phải"


def test_trend_still_refuses_to_bridge_a_missing_week_after_filtering():
    """Bỏ tuần rỗng khỏi trục x không được biến hai tuần cách nhau thành liền mạch."""
    observed = run(page_text(), r"""
const full=(date)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_rate:.8,reopen_lifetime_rate:.2});
globalThis.__test.renderTrend([full("2026-07-06"),{cohort_week:"2026-07-13",has_data:false,total_tickets:0},full("2026-07-20")]);
const svg=document.getElementById("trendChart");
process.stdout.write(JSON.stringify({polylines:svg.children.filter(node=>node.tagName==="polyline").length}));
""")
    assert observed["polylines"] == 4


def test_trend_has_full_text_tooltips_and_navigation_highlight_hook():
    observed = run(page_text(), r"""
globalThis.__test.renderTrend([{cohort_week:"2026-07-20",cohort_status:"complete",has_data:true,total_tickets:10,ai_first_rate:.8,reopen_lifetime_rate:.2}]);
const svg=document.getElementById("trendChart");
process.stdout.write(JSON.stringify({chart:svg.textContent,viewBox:svg.getAttribute("viewBox"),namespaces:svg.children.map(node=>node.namespaceURI)}));
""")
    assert "10 ticket" in observed["chart"]
    assert "AI First 80,0%" in observed["chart"]
    assert "Reopen 20,0%" in observed["chart"]
    assert observed["viewBox"] == "0 0 320 160"
    assert set(observed["namespaces"]) == {"http://www.w3.org/2000/svg"}
    page = page_text()
    assert "IntersectionObserver" in page
    assert 'aria-current","location"' in page


def test_trend_caption_matches_solid_ai_and_dashed_reopen_rendered_encoding():
    page = page_text()
    assert re.search(r"\.line-reopen\{[^}]*stroke-dasharray:6 4", page)
    assert not re.search(r"\.line-ai\{[^}]*stroke-dasharray", page)
    observed = run(page, r"""
const full=(date,ai,reopen)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_rate:ai,reopen_lifetime_rate:reopen});
globalThis.__test.renderTrend([full("2026-07-13",.7,.1),full("2026-07-20",.8,.2)]);
const svg=document.getElementById("trendChart"),lines=svg.children.filter(node=>node.tagName==="polyline");
const byClass=Object.fromEntries(lines.map(line=>[line.getAttribute("class"),line.getAttribute("stroke-dasharray")]));
process.stdout.write(JSON.stringify({byClass,caption:document.getElementById("trendCaption").textContent}));
""")
    assert observed["byClass"] == {"line-ai": None, "line-reopen": "6 4"}
    assert "đường liền xanh là AI First" in observed["caption"]
    assert "đường đứt vàng là reopen" in observed["caption"]


def test_trend_breaks_lines_at_missing_weeks_instead_of_bridging_the_gap():
    observed = run(page_text(), r"""
const full=(date)=>({cohort_week:date,cohort_status:"complete",has_data:true,total_tickets:10,ai_first_rate:.8,reopen_lifetime_rate:.2});
globalThis.__test.renderTrend([full("2026-07-06"),{cohort_week:"2026-07-13",has_data:false,total_tickets:0},full("2026-07-20")]);
const svg=document.getElementById("trendChart");
process.stdout.write(JSON.stringify({polylines:svg.children.filter(node=>node.tagName==="polyline").length}));
""")
    assert observed["polylines"] == 4


def test_static_palette_meets_text_and_interactive_non_text_contrast():
    def luminance(value: str) -> float:
        rgb = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        channels = [item / 12.92 if item <= .04045 else ((item + .055) / 1.055) ** 2.4 for item in rgb]
        return .2126 * channels[0] + .7152 * channels[1] + .0722 * channels[2]

    def ratio(first: str, second: str) -> float:
        values = sorted((luminance(first), luminance(second)), reverse=True)
        return (values[0] + .05) / (values[1] + .05)

    for foreground, background in (
        ("#111418", "#FFFFFF"), ("#5F6368", "#FFFFFF"), ("#087F47", "#FFFFFF"),
        ("#D93025", "#FFFFFF"), ("#8A5A00", "#FFFFFF"), ("#FFFFFF", "#0068FF"),
        ("#E9EAEE", "#111418"), ("#B8BEC7", "#111418"), ("#5DDB93", "#111418"),
        ("#FF8A80", "#111418"), ("#FFD166", "#111418"),
    ):
        assert ratio(foreground, background) >= 4.5
    for foreground, background in (
        ("#767676", "#FFFFFF"), ("#5675A8", "#FFFFFF"),
        ("#A45F00", "#FFFFFF"), ("#7C8794", "#111418"), ("#FFD166", "#111418"),
    ):
        assert ratio(foreground, background) >= 3


def test_root_keeps_security_headers():
    class Manager:
        def close(self): pass
    with TestClient(create_app(Manager(), settings=WebSettings("off", "X-Forwarded-User"))) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    policy = response.headers["content-security-policy"]
    for directive in ("default-src 'self'", "base-uri 'none'", "object-src 'none'", "frame-ancestors 'none'", "form-action 'self'", "connect-src 'self'", "worker-src 'none'"):
        assert directive in policy
    assert "'unsafe-inline'" not in policy
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
    assert PAGE.is_file()
