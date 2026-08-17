#!/usr/bin/env python3
"""
Веб-дашборд над order_ledger.

Локальный, без внешних зависимостей и CDN: только стандартная библиотека,
стили и скрипты инлайн. Работает офлайн.

    python3 tools/dashboard.py                 # http://0.0.0.0:8080
    python3 tools/dashboard.py --port 9000 --db data/ledger.json

Данные — тот же data/ledger.json, что и у CLI. Инструменты взаимозаменяемы.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent))
from order_ledger import (  # noqa: E402
    Order, ROUTES, REASONS, load, save, find, DB_DEFAULT, d,
)

DB: Path = DB_DEFAULT
TOKEN: str | None = None


# --------------------------------------------------------------------------- data

def snapshot() -> dict:
    orders = load(DB)
    act = [o for o in orders if o.status != "lost"]
    invested = sum(o.invested() for o in act)
    revenue = sum(o.sold_price for o in act)
    refunded = sum(o.refund_amount for o in act)
    cust_ref = sum(o.customer_refunded for o in act)
    net = sum(o.net() for o in act)
    pending = sum(o.pending_recovery() for o in orders)
    gap = sum(o.capital_gap() for o in orders)
    lost = sum(o.invested() for o in orders if o.status == "lost")
    claimed = [o for o in orders if o.status in ("claimed", "refunded")]
    claim_rate = (len(claimed) / len(orders) * 100) if orders else 0.0
    fx_losses = [o.fx_loss() for o in orders if o.fx_loss() is not None]
    fx_total = round(sum(fx_losses), 2) if fx_losses else 0.0

    # Возврат одобрен > 28 дн. (≈20 раб., research/17 §2), зачисление не отмечено → ARN
    refund_wait = []
    for o in orders:
        if (o.status == "refunded" and o.refund_date
                and o.refund_amount > 0 and o.card_refunded <= 0):
            age = (date.today() - d(o.refund_date)).days
            if age > 28:
                refund_wait.append({"id": o.order_id, "title": o.title, "age": age})

    rows = []
    for o in sorted(orders, key=lambda x: (x.days_left() is None, x.days_left() or 0)):
        dl, why = o.deadline()
        age = None
        if o.claim_opened:
            age = (date.today() - d(o.claim_opened)).days
        rows.append({
            "id": o.order_id, "title": o.title, "route": o.route,
            "route_label": ROUTES.get(o.route, o.route),
            "invested": round(o.invested(), 2), "sold": round(o.sold_price, 2),
            "refund": round(o.refund_amount, 2),
            "customer_refund": round(o.customer_refunded, 2),
            "net": round(o.net(), 2), "status": o.status,
            "deadline": dl.isoformat() if dl else None, "deadline_why": why,
            "days_left": o.days_left(), "urgency": o.urgency(),
            "free_return": o.free_return, "currency": o.currency,
            "claim_reason": REASONS.get(o.claim_reason, o.claim_reason),
            "claim_age": age, "pending": round(o.pending_recovery(), 2),
            "gap": round(o.capital_gap(), 2),
            "card_charged": round(o.card_charged, 2), "card_refunded": round(o.card_refunded, 2),
            "card_currency": o.card_currency,
            "fx_loss": round(o.fx_loss(), 2) if o.fx_loss() is not None else None,
            "customer": o.customer, "notes": o.notes,
            "shipped": o.shipped, "delivered": o.delivered, "confirmed": o.confirmed,
        })

    by_route: dict[str, dict] = {}
    for o in orders:
        b = by_route.setdefault(o.route, {"count": 0, "net": 0.0, "invested": 0.0, "claims": 0})
        b["count"] += 1
        b["net"] += o.net()
        b["invested"] += o.invested()
        if o.status in ("claimed", "refunded"):
            b["claims"] += 1
    for b in by_route.values():
        b["net"] = round(b["net"], 2)
        b["invested"] = round(b["invested"], 2)

    return {
        "kpi": {
            "orders": len(orders), "active": len(act),
            "invested": round(invested, 2), "revenue": round(revenue, 2),
            "refunded": round(refunded, 2), "customer_refunded": round(cust_ref, 2),
            "net": round(net, 2), "pending": round(pending, 2),
            "gap": round(gap, 2), "lost": round(lost, 2),
            "margin": round(net / invested * 100, 1) if invested else 0.0,
            "claim_rate": round(claim_rate, 1),
            "fx_loss_total": fx_total,
        },
        "orders": rows,
        "routes": by_route,
        "refund_wait": refund_wait,
        "meta": {"routes": ROUTES, "reasons": REASONS, "today": date.today().isoformat()},
    }


# --------------------------------------------------------------------------- html

PAGE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AliExpress Ledger</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
 background:#0f1218;color:#e6e9ef;padding:20px;max-width:1400px;margin:0 auto}
h1{font-size:20px;font-weight:600;margin-bottom:2px}
.sub{color:#8b93a7;font-size:12px;margin-bottom:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:20px}
.card{background:#171b24;border:1px solid #232935;border-radius:10px;padding:14px}
.card .lbl{color:#8b93a7;font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}
.card .val{font-size:22px;font-weight:600;font-variant-numeric:tabular-nums}
.card .hint{font-size:11px;color:#6b7488;margin-top:4px}
.pos{color:#4ade80}.neg{color:#f87171}.warn{color:#fbbf24}.mut{color:#8b93a7}
.alert{background:#2a1f1f;border:1px solid #5c2d2d;border-radius:10px;padding:12px 14px;
 margin-bottom:16px;font-size:13px}
.alert b{color:#fca5a5}
section{background:#171b24;border:1px solid #232935;border-radius:10px;padding:16px;margin-bottom:16px}
section h2{font-size:14px;font-weight:600;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.badge{background:#232935;color:#8b93a7;border-radius:20px;padding:2px 8px;font-size:11px;font-weight:400}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:#8b93a7;font-weight:500;font-size:11px;text-transform:uppercase;
 letter-spacing:.4px;padding:8px 10px;border-bottom:1px solid #232935;white-space:nowrap}
td{padding:9px 10px;border-bottom:1px solid #1c212b;vertical-align:middle}
tr:last-child td{border-bottom:none}
tr.row:hover{background:#1c212b;cursor:pointer}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.tag{display:inline-block;padding:2px 7px;border-radius:5px;font-size:11px;font-weight:500;white-space:nowrap}
.t-crit{background:#4c1d1d;color:#fca5a5}.t-urg{background:#4a3410;color:#fcd34d}
.t-ok{background:#14331f;color:#86efac}.t-exp{background:#3f1010;color:#f87171}
.t-mut{background:#232935;color:#8b93a7}
.st{font-size:11px;padding:2px 7px;border-radius:5px;background:#232935;color:#a5adc0}
.st-claimed{background:#3d2f10;color:#fcd34d}.st-refunded{background:#14331f;color:#86efac}
.st-lost{background:#3f1010;color:#f87171}
.bar{height:5px;background:#232935;border-radius:3px;overflow:hidden;margin-top:6px}
.bar>div{height:100%;background:#3b82f6}
form{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;align-items:end}
label{display:block;font-size:11px;color:#8b93a7;margin-bottom:4px}
input,select{width:100%;background:#0f1218;border:1px solid #2c3342;color:#e6e9ef;
 border-radius:7px;padding:8px 10px;font-size:13px;font-family:inherit}
input:focus,select:focus{outline:none;border-color:#3b82f6}
button{background:#2563eb;color:#fff;border:none;border-radius:7px;padding:9px 16px;
 font-size:13px;font-weight:500;cursor:pointer;font-family:inherit}
button:hover{background:#1d4ed8}
button.sec{background:#232935;color:#c3cad9}button.sec:hover{background:#2c3342}
.act{display:flex;gap:6px;flex-wrap:wrap}
.act button{padding:5px 10px;font-size:11px}
.empty{color:#6b7488;text-align:center;padding:30px;font-size:13px}
.det{background:#0f1218;font-size:12px;color:#a5adc0}
.det td{padding:12px 14px}
.det .k{color:#6b7488;display:inline-block;min-width:120px}
.note{padding:3px 0;border-bottom:1px solid #1c212b}
.msg{position:fixed;bottom:20px;right:20px;background:#14331f;border:1px solid #2d5c3d;
 color:#86efac;padding:11px 16px;border-radius:8px;font-size:13px;opacity:0;
 transition:opacity .25s;pointer-events:none;z-index:99}
.msg.show{opacity:1}.msg.err{background:#2a1f1f;border-color:#5c2d2d;color:#fca5a5}
@media(max-width:640px){body{padding:12px}.hide-s{display:none}}
</style></head><body>

<h1>AliExpress Ledger</h1>
<div class="sub">Дедлайны Buyer Protection · P&amp;L · оборотный капитал<span id="today"></span></div>

<div id="alerts"></div>
<div class="grid" id="kpi"></div>

<section>
  <h2>Добавить заказ</h2>
  <form id="addf" onsubmit="return addOrder(event)">
    <div><label>ID заказа</label><input name="id" required placeholder="AE-1001"></div>
    <div><label>Товар</label><input name="title" required placeholder="Название"></div>
    <div><label>Закупка</label><input name="cost" type="number" step="0.01" value="0"></div>
    <div><label>Доставка/пошлина</label><input name="ship" type="number" step="0.01" value="0"></div>
    <div><label>Цена продажи</label><input name="sold" type="number" step="0.01" value="0"></div>
    <div><label>Отправлен</label><input name="shipped" type="date"></div>
    <div><label>Маршрут</label><select name="route" id="routes"></select></div>
    <div><label>Free Return</label><select name="free_return"><option value="0">нет</option><option value="1">да</option></select></div>
    <div><button type="submit">Добавить</button></div>
  </form>
</section>

<section>
  <h2>Заказы <span class="badge" id="cnt">0</span></h2>
  <div id="tbl"></div>
</section>

<section>
  <h2>По маршрутам</h2>
  <div id="routes-tbl"></div>
</section>

<div class="msg" id="msg"></div>

<script>
var DATA=null, open_=null;
function f(n){return (n<0?"":"")+n.toFixed(2)}
function cls(n){return n>0?"pos":(n<0?"neg":"mut")}
function esc(s){var e=document.createElement("i");e.textContent=s==null?"":String(s);return e.innerHTML}

function toast(t,err){var m=document.getElementById("msg");m.textContent=t;
 m.className="msg show"+(err?" err":"");setTimeout(function(){m.className="msg"},2600)}

function api(path,body,cb){
 var x=new XMLHttpRequest();x.open(body?"POST":"GET",path,true);
 x.setRequestHeader("Content-Type","application/json");
 x.onload=function(){var r={};try{r=JSON.parse(x.responseText)}catch(e){}
  if(x.status>=200&&x.status<300){cb&&cb(r)}else{toast(r.error||"Ошибка "+x.status,1)}};
 x.onerror=function(){toast("Нет связи с сервером",1)};
 x.send(body?JSON.stringify(body):null)}

function load(cb){api("/api/data",null,function(r){DATA=r;render();cb&&cb()})}

function render(){
 var k=DATA.kpi;
 document.getElementById("today").textContent=" · "+DATA.meta.today;
 document.getElementById("cnt").textContent=k.orders;

 var kp=[
  ["Итог",f(k.net),cls(k.net),k.margin+"% маржи"],
  ["Вложено",f(k.invested),"mut",k.active+" активных"],
  ["Выручка",f(k.revenue),"mut","от продаж"],
  ["Возвращено",f(k.refunded),k.refunded>0?"pos":"mut","поставщиком"],
  ["Ожидается",f(k.pending),k.pending>0?"warn":"mut","по спорам"],
  ["Разрыв оборотки",f(k.gap),k.gap>0?"neg":"mut","клиенту вернул"],
  ["Доля споров",k.claim_rate+"%",k.claim_rate>20?"neg":(k.claim_rate>10?"warn":"pos"),"от заказов"],
  ["FX-потери",f(k.fx_loss_total),k.fx_loss_total>0?"neg":"mut","на конвертации"],
  ["Потери",f(k.lost),k.lost>0?"neg":"mut","списано"]];
 document.getElementById("kpi").innerHTML=kp.map(function(c){
  return '<div class="card"><div class="lbl">'+c[0]+'</div><div class="val '+c[2]+'">'+c[1]+
   '</div><div class="hint">'+c[3]+'</div></div>'}).join("");

 var al=[];
 var hot=DATA.orders.filter(function(o){return (o.urgency=="КРИТИЧНО"||o.urgency=="ПРОСРОЧЕНО")});
 if(hot.length)al.push("<b>"+hot.length+" заказ(ов) с горящим дедлайном.</b> Открывай спор до истечения окна — потом уже нельзя.");
 if(k.claim_rate>20)al.push("<b>Доля споров "+k.claim_rate+"%.</b> Высокая доля повышает риск ограничений на аккаунте (research/06).");
 if(k.gap>0)al.push("<b>Разрыв оборотки "+f(k.gap)+".</b> Возвращено клиентам больше, чем получено от поставщиков.");
 var stale=DATA.orders.filter(function(o){return o.claim_age!=null&&o.claim_age>30&&o.status=="claimed"});
 if(stale.length)al.push("<b>"+stale.length+" спор(ов) висят дольше 30 дней.</b> Пора эскалировать к платформе.");
 if(DATA.refund_wait&&DATA.refund_wait.length)al.push("<b>"+DATA.refund_wait.length+
  " возврат(ов) одобрены &gt;28 дн. назад, зачисление не отмечено:</b> "+
  DATA.refund_wait.map(function(w){return w.id+" ("+w.age+" дн.)"}).join(", ")+
  ". Проверь выписку; денег нет — запроси ARN у поддержки (research/17).");
 document.getElementById("alerts").innerHTML=al.map(function(a){
  return '<div class="alert">'+a+'</div>'}).join("");

 var os=DATA.orders;
 if(!os.length){document.getElementById("tbl").innerHTML='<div class="empty">Заказов пока нет. Добавь первый через форму выше.</div>'}
 else{
  var h='<table><thead><tr><th>Заказ</th><th>Товар</th><th class="hide-s">Маршрут</th>'+
   '<th class="num">Влож.</th><th class="num">Прод.</th><th class="num">Возвр.</th>'+
   '<th class="num">Итог</th><th>Дедлайн</th><th class="num">Ост.</th><th>Статус</th></tr></thead><tbody>';
  os.forEach(function(o){
   var u={"КРИТИЧНО":"t-crit","СРОЧНО":"t-urg","ок":"t-ok","ПРОСРОЧЕНО":"t-exp"}[o.urgency]||"t-mut";
   h+='<tr class="row" onclick="tog(\\''+o.id+'\\')"><td><b>'+esc(o.id)+'</b>'+(o.free_return?' <span class="tag t-ok">FR</span>':'')+'</td>'+
    '<td>'+esc(o.title)+'</td><td class="hide-s mut">'+esc(o.route)+'</td>'+
    '<td class="num">'+f(o.invested)+'</td><td class="num">'+f(o.sold)+'</td>'+
    '<td class="num">'+f(o.refund)+'</td><td class="num '+cls(o.net)+'">'+f(o.net)+'</td>'+
    '<td class="mut">'+(o.deadline||"—")+'</td>'+
    '<td class="num"><span class="tag '+u+'">'+(o.days_left==null?"—":o.days_left)+'</span></td>'+
    '<td><span class="st st-'+o.status+'">'+o.status+'</span></td></tr>';
   if(open_==o.id){
    h+='<tr class="det"><td colspan="10"><div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">'+
     '<div><div><span class="k">Маршрут:</span>'+esc(o.route_label)+'</div>'+
     '<div><span class="k">Окно:</span>'+esc(o.deadline_why)+'</div>'+
     '<div><span class="k">Отправлен:</span>'+(o.shipped||"—")+'</div>'+
     '<div><span class="k">Доставлен:</span>'+(o.delivered||"—")+'</div>'+
     '<div><span class="k">Подтверждён:</span>'+(o.confirmed||"—")+'</div>'+
     (o.customer?'<div><span class="k">Клиент:</span>'+esc(o.customer)+'</div>':'')+
     (o.claim_reason?'<div><span class="k">Претензия:</span>'+esc(o.claim_reason)+
       (o.claim_age!=null?' ('+o.claim_age+' дн.)':'')+'</div>':'')+
     (o.customer_refund>0?'<div><span class="k">Клиенту вернул:</span>'+f(o.customer_refund)+'</div>':'')+
     (o.card_charged>0?'<div><span class="k">Списано с карты:</span>'+f(o.card_charged)+' '+esc(o.card_currency)+'</div>':'')+
     (o.card_refunded>0?'<div><span class="k">Пришло на карту:</span>'+f(o.card_refunded)+' '+esc(o.card_currency)+'</div>':'')+
     (o.fx_loss!=null?'<div><span class="k">FX-потеря:</span><span class="'+(o.fx_loss>0?'neg':'pos')+'">'+f(o.fx_loss)+' '+esc(o.card_currency)+'</span></div>':'')+
     '</div><div>'+
     (o.notes.length?'<div class="k" style="margin-bottom:4px">Заметки:</div>'+
       o.notes.map(function(n){return '<div class="note">'+esc(n)+'</div>'}).join(""):'<span class="mut">Заметок нет</span>')+
     '</div></div>'+
     '<div class="act" style="margin-top:12px">'+
     '<button class="sec" onclick="event.stopPropagation();mark(\\''+o.id+'\\',\\'delivered\\')">Доставлен</button>'+
     '<button class="sec" onclick="event.stopPropagation();mark(\\''+o.id+'\\',\\'confirm\\')">Подтвердить получение</button>'+
     '<button class="sec" onclick="event.stopPropagation();claim(\\''+o.id+'\\')">Открыть спор</button>'+
     '<button class="sec" onclick="event.stopPropagation();refund(\\''+o.id+'\\')">Возврат получен</button>'+
     '<button class="sec" onclick="event.stopPropagation();charged(\\''+o.id+'\\')">Списание с карты</button>'+
     '<button class="sec" onclick="event.stopPropagation();cardref(\\''+o.id+'\\')">Пришло на карту</button>'+
     '<button class="sec" onclick="event.stopPropagation();custref(\\''+o.id+'\\')">Вернул клиенту</button>'+
     '<button class="sec" onclick="event.stopPropagation();note(\\''+o.id+'\\')">Заметка</button>'+
     '<button class="sec" onclick="event.stopPropagation();mark(\\''+o.id+'\\',\\'close\\')">Закрыть</button>'+
     '</div></td></tr>'}
  });
  document.getElementById("tbl").innerHTML=h+'</tbody></table>'}

 var rt=DATA.routes,keys=Object.keys(rt);
 if(!keys.length){document.getElementById("routes-tbl").innerHTML='<div class="empty">Нет данных</div>'}
 else{
  var mx=Math.max.apply(null,keys.map(function(x){return Math.abs(rt[x].net)}))||1;
  var rh='<table><thead><tr><th>Маршрут</th><th class="num">Заказов</th>'+
   '<th class="num">Вложено</th><th class="num">Итог</th><th class="num">Споров</th><th></th></tr></thead><tbody>';
  keys.forEach(function(x){var r=rt[x];
   rh+='<tr><td>'+esc(DATA.meta.routes[x]||x)+'</td><td class="num">'+r.count+'</td>'+
    '<td class="num">'+f(r.invested)+'</td><td class="num '+cls(r.net)+'">'+f(r.net)+'</td>'+
    '<td class="num">'+r.claims+'</td><td style="width:120px"><div class="bar"><div style="width:'+
    (Math.abs(r.net)/mx*100)+'%;background:'+(r.net<0?"#f87171":"#4ade80")+'"></div></div></td></tr>'});
  document.getElementById("routes-tbl").innerHTML=rh+'</tbody></table>'}
}

function tog(id){open_=(open_==id?null:id);render()}

function addOrder(e){e.preventDefault();
 var fd=new FormData(e.target),o={};
 fd.forEach(function(v,k){o[k]=v});
 o.cost=parseFloat(o.cost||0);o.ship=parseFloat(o.ship||0);o.sold=parseFloat(o.sold||0);
 o.free_return=o.free_return=="1";
 api("/api/add",o,function(){e.target.reset();load();toast("Заказ добавлен")});
 return false}

function mark(id,what){
 var dt=(what=="close")?null:prompt(what=="delivered"?"Дата доставки (ГГГГ-ММ-ДД):":"Дата подтверждения (ГГГГ-ММ-ДД):",DATA.meta.today);
 if(what!="close"&&!dt)return;
 api("/api/"+what,{id:id,date:dt},function(){load();toast("Обновлено")})}

function claim(id){
 var rs=Object.keys(DATA.meta.reasons);
 var t="Причина спора:\\n"+rs.map(function(r,i){return (i+1)+". "+DATA.meta.reasons[r]}).join("\\n");
 var n=prompt(t,"1");if(!n)return;
 var r=rs[parseInt(n,10)-1];if(!r){toast("Неверный номер",1);return}
 var amt=prompt("Запрашиваемая сумма:","");
 api("/api/claim",{id:id,reason:r,ask:parseFloat(amt||0)},function(){load();toast("Спор открыт. Не закрывай его до решения.")})}

function refund(id){var a=prompt("Сумма возврата от поставщика:","");if(!a)return;
 api("/api/refunded",{id:id,amount:parseFloat(a)},function(){load();toast("Возврат записан")})}

function custref(id){var a=prompt("Сумма возврата клиенту:","");if(!a)return;
 api("/api/customer-refund",{id:id,amount:parseFloat(a)},function(){load();toast("Записано")})}

function charged(id){var a=prompt("Списано с карты по выписке (в валюте карты):","");if(!a)return;
 var c=prompt("Валюта карты:","UAH")||"UAH";
 api("/api/charged",{id:id,amount:parseFloat(a),currency:c},function(){load();toast("Списание записано")})}

function cardref(id){var a=prompt("Зачислено на карту по выписке (в валюте карты):","");if(!a)return;
 api("/api/refund-received",{id:id,amount:parseFloat(a)},function(){load();toast("Зачисление записано")})}

function note(id){var t=prompt("Заметка:","");if(!t)return;
 api("/api/note",{id:id,text:t},function(){load();toast("Заметка добавлена")})}

api("/api/data",null,function(r){DATA=r;
 document.getElementById("routes").innerHTML=Object.keys(r.meta.routes).map(function(k){
  return '<option value="'+k+'">'+esc(r.meta.routes[k])+'</option>'}).join("");
 render()});
setInterval(function(){load()},30000);
</script></body></html>"""


# --------------------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):  # тише
        pass

    # ---- авторизация (T-039): токен через --token или env DASHBOARD_TOKEN ----
    def _authorized(self) -> bool:
        if not TOKEN:
            return True  # локальный режим без токена — как раньше
        qs = parse_qs(urlparse(self.path).query)
        if qs.get("token", [None])[0] == TOKEN:
            return True
        cookie = self.headers.get("Cookie", "") or ""
        return f"dash_token={TOKEN}" in cookie

    def _deny(self) -> None:
        body = ("<!DOCTYPE html><html lang=ru><meta charset=utf-8>"
                "<body style='font-family:sans-serif;background:#0f1218;color:#e6e9ef;"
                "display:flex;align-items:center;justify-content:center;height:100vh'>"
                "<div><h2>401 — нужен токен</h2>"
                "<p>Открой дашборд как <code>/?token=&lt;твой токен&gt;</code> — "
                "дальше токен запомнится в cookie.</p></div></body></html>").encode("utf-8")
        self._send(401, body, "text/html; charset=utf-8")

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:
        if not self._authorized():
            return self._deny()
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            extra = None
            if TOKEN:  # токен пришёл в query → закрепить в cookie
                extra = {"Set-Cookie": f"dash_token={TOKEN}; Path=/; HttpOnly; SameSite=Strict"}
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8", extra)
        elif path == "/api/data":
            self._json(snapshot())
        elif path == "/api/export":
            orders = load(DB)
            lines = ["order_id,title,route,invested,sold,supplier_refund,customer_refund,net,status,deadline,days_left"]
            for o in orders:
                dl, _ = o.deadline()
                lines.append(",".join([
                    o.order_id, '"' + o.title.replace('"', '""') + '"', o.route,
                    f"{o.invested():.2f}", f"{o.sold_price:.2f}", f"{o.refund_amount:.2f}",
                    f"{o.customer_refunded:.2f}", f"{o.net():.2f}", o.status,
                    dl.isoformat() if dl else "", str(o.days_left()),
                ]))
            self._send(200, "\n".join(lines).encode("utf-8"), "text/csv; charset=utf-8")
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if not self._authorized():
            return self._json({"error": "unauthorized"}, 401)
        path = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json({"error": "bad json"}, 400)

        try:
            orders = load(DB)
            if path == "/api/add":
                oid = (data.get("id") or "").strip()
                if not oid:
                    return self._json({"error": "нужен id"}, 400)
                if any(o.order_id == oid for o in orders):
                    return self._json({"error": f"{oid} уже существует"}, 400)
                o = Order(
                    order_id=oid, title=(data.get("title") or "").strip() or oid,
                    cost=float(data.get("cost") or 0), ship_cost=float(data.get("ship") or 0),
                    sold_price=float(data.get("sold") or 0),
                    route=data.get("route") or "ua-direct",
                    customer=data.get("customer") or "",
                    shipped=data.get("shipped") or None,
                    free_return=bool(data.get("free_return")),
                )
                orders.append(o)
            else:
                o = find(orders, data.get("id", ""))
                today = date.today().isoformat()
                if path == "/api/delivered":
                    o.delivered = data.get("date") or today
                elif path == "/api/confirm":
                    o.confirmed = data.get("date") or today
                elif path == "/api/claim":
                    o.status = "claimed"
                    o.claim_reason = data.get("reason", "")
                    o.claim_asked = float(data.get("ask") or 0) or o.invested()
                    o.claim_opened = data.get("date") or today
                    o.notes.append(f"{o.claim_opened}: заявка — "
                                   f"{REASONS.get(o.claim_reason, o.claim_reason)}, "
                                   f"запрошено {o.claim_asked:.2f}")
                elif path == "/api/refunded":
                    o.refund_amount = float(data.get("amount") or 0)
                    o.refund_date = data.get("date") or today
                    o.status = "refunded"
                    o.notes.append(f"{o.refund_date}: возврат от поставщика {o.refund_amount:.2f}")
                elif path == "/api/customer-refund":
                    o.customer_refunded = float(data.get("amount") or 0)
                    o.customer_refund_date = data.get("date") or today
                    o.notes.append(f"{o.customer_refund_date}: возврат клиенту {o.customer_refunded:.2f}")
                elif path == "/api/charged":
                    o.card_charged = float(data.get("amount") or 0)
                    o.card_currency = (data.get("currency") or "UAH").strip() or "UAH"
                    o.notes.append(f"{today}: списано с карты {o.card_charged:.2f} {o.card_currency}")
                elif path == "/api/refund-received":
                    o.card_refunded = float(data.get("amount") or 0)
                    o.notes.append(f"{today}: возврат на карту {o.card_refunded:.2f} {o.card_currency}")
                elif path == "/api/note":
                    o.notes.append(f"{today}: {data.get('text', '')}")
                elif path == "/api/close":
                    o.status = "closed"
                else:
                    return self._json({"error": "not found"}, 404)
            save(DB, orders)
            self._json({"ok": True})
        except SystemExit as e:
            self._json({"error": str(e)}, 404)
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def main() -> None:
    global DB, TOKEN
    p = argparse.ArgumentParser(description="Веб-дашборд Order Ledger")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--db", type=Path, default=DB_DEFAULT)
    p.add_argument("--token", default=os.environ.get("DASHBOARD_TOKEN") or None,
                   help="токен доступа (или env DASHBOARD_TOKEN); без него — режим без авторизации")
    a = p.parse_args()
    DB = a.db
    TOKEN = a.token
    DB.parent.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"Дашборд: http://{a.host}:{a.port}  (данные: {DB})")
    if TOKEN:
        print(f"  Авторизация включена: открой /?token=<токен> (значение не печатаем)")
    else:
        print("  ⚠ Без токена — только для локального запуска. "
              "Для удалённого доступа: --token или env DASHBOARD_TOKEN (хранить в vault).")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлен")


if __name__ == "__main__":
    main()
