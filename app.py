# app.py
from flask import Flask, jsonify, abort, send_file, render_template_string
import os
import math
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError

_engine = None

def get_engine():
    global _engine
    if _engine is not None:
        return _engine
    db_url = os.getenv("DB_URL")
    if not db_url:
        raise RuntimeError("Missing DB_URL (or DATABASE_URL) environment variable.")
    # Normalize old 'postgres://' scheme to 'postgresql://'
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]
    _engine = create_engine(
        db_url,
        pool_pre_ping=True,
    )
    return _engine

HOME_PAGE = r"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Neurosynth — A minus B</title>
<style>
:root{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#1e293b;background:#f8fafc}
body{margin:0}.wrap{max-width:780px;margin:50px auto;padding:0 20px}
h1{font-size:28px;margin-bottom:8px}p{color:#64748b;line-height:1.55}
.card{background:white;border:1px solid #e2e8f0;border-radius:12px;padding:22px;margin-top:18px}
h2{font-size:17px;margin-top:0}.fields{display:grid;grid-template-columns:1fr 1fr;gap:12px}
label{display:block;font-size:13px;font-weight:600;margin-bottom:7px}
input{width:100%;box-sizing:border-box;border:1px solid #cbd5e1;border-radius:7px;padding:10px;font-size:15px}
button{background:#1d4ed8;color:white;border:0;border-radius:7px;padding:11px 18px;cursor:pointer;margin-top:13px}
button:disabled{opacity:.6;cursor:wait}.muted{font-size:13px}#results{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5f9;border-radius:7px;padding:16px;max-height:330px;overflow:auto;font:13px/1.6 ui-monospace,monospace}
.stat{font-weight:bold;font-size:23px;color:#1d4ed8;margin-top:14px}.hidden{display:none}
@media(max-width:560px){.fields{grid-template-columns:1fr}.wrap{margin:25px auto}}
</style></head>
<body><main class="wrap">
<h1>Neurosynth Dissociation</h1>
<p>比較與 A 有關、但與 B 無關的 studies（A − B）。結果直接由 PostgreSQL 資料庫查詢。</p>
<section class="card"><h2>1. By terms</h2>
<div class="fields"><div><label for="termA">Term A</label><input id="termA" value="memory"></div>
<div><label for="termB">Term B</label><input id="termB" value="attention"></div></div>
<button type="button" onclick="searchTerms()">Search terms</button>
<p class="muted">以 Neurosynth annotations 的 TF-IDF term 欄位，weight &gt; 0 為符合條件。</p></section>
<section class="card"><h2>2. By MNI coordinates</h2>
<div class="fields"><div><label for="coordA">Coordinate A (x_y_z)</label><input id="coordA" value="0_-52_26"></div>
<div><label for="coordB">Coordinate B (x_y_z)</label><input id="coordB" value="-2_50_-6"></div></div>
<button type="button" onclick="searchCoords()">Search coordinates</button>
<p class="muted">以 6 mm 三維距離搜尋，取 A − B 的研究 ID。</p></section>
<section class="card" aria-live="polite"><h2>Search results</h2>
<div id="status" class="muted">選擇上方一種搜尋方式。</div>
<div id="count" class="stat hidden"></div>
<pre id="results" class="hidden"></pre>
</section>
<p class="muted">API: <a href="/test_db">Database status</a> · <a href="/img">Image</a></p>
</main><script>
async function loadResult(url){
 const status=document.getElementById('status'), count=document.getElementById('count'), output=document.getElementById('results');
 status.textContent='Searching…';count.classList.add('hidden');output.classList.add('hidden');
 try {
  const response=await fetch(url);
  const data=await response.json();
  if(!response.ok) throw Error(data.error||data.message||('HTTP '+response.status));
  count.textContent='Matching studies: '+data.count;count.classList.remove('hidden');
  output.textContent=JSON.stringify(data,null,2);output.classList.remove('hidden');
  status.textContent='A − B results';
 } catch(e){status.textContent='Search failed: '+e.message;}
}
function searchTerms(){
 const a=document.getElementById('termA').value.trim().replaceAll(' ','_');
 const b=document.getElementById('termB').value.trim().replaceAll(' ','_');
 if(!a||!b){alert('Please enter both terms');return;}
 loadResult('/dissociate/terms/'+encodeURIComponent(a)+'/'+encodeURIComponent(b));
}
function searchCoords(){
 const a=document.getElementById('coordA').value.trim(),b=document.getElementById('coordB').value.trim();
 const valid=s=>s.split('_').length===3&&s.split('_').every(v=>v!==''&&Number.isFinite(Number(v)));
 if(!valid(a)||!valid(b)){alert('Use x_y_z, e.g. 0_-52_26');return;}
 loadResult('/dissociate/locations/'+encodeURIComponent(a)+'/'+encodeURIComponent(b));
}
</script></body></html>"""

def create_app():
    app = Flask(__name__)

    @app.get("/", endpoint="health")
    def health():
        return render_template_string(HOME_PAGE)

    @app.get("/img", endpoint="show_img")
    def show_img():
        return send_file("amygdala.gif", mimetype="image/gif")

    @app.get("/terms/<term>/studies", endpoint="terms_studies")
    def get_studies_by_term(term):
        return term

    @app.get("/locations/<coords>/studies", endpoint="locations_studies")
    def get_studies_by_coordinates(coords):
        x, y, z = map(int, coords.split("_"))
        return jsonify([x, y, z])

    # Required functional dissociation endpoints (A minus B).
    # A study counts only once, even if it has multiple contrasts or foci.
    @app.get("/dissociate/terms/<term_a>/<term_b>")
    def dissociate_terms(term_a, term_b):
        a = term_a.replace("_", " ").strip().lower()
        b = term_b.replace("_", " ").strip().lower()
        if not a or not b:
            abort(400, description="Both terms are required")

        sql = text("""
            SELECT DISTINCT study_id
            FROM ns.annotations_terms
            WHERE term IN (:a, :a_prefixed) AND weight > 0
            EXCEPT
            SELECT DISTINCT study_id
            FROM ns.annotations_terms
            WHERE term IN (:b, :b_prefixed) AND weight > 0
        """)
        with get_engine().connect() as conn:
            ids = sorted(conn.execute(sql, {
                "a": a, "b": b,
                "a_prefixed": "terms_abstract_tfidf__" + a,
                "b_prefixed": "terms_abstract_tfidf__" + b,
            }).scalars().all())
        return jsonify({"term_a": a, "term_b": b,
                        "count": len(ids), "study_ids": ids})

    @app.get("/dissociate/locations/<coords_a>/<coords_b>")
    def dissociate_locations(coords_a, coords_b):
        def parse_coords(value):
            try:
                items = [float(v) for v in value.split("_")]
            except ValueError:
                abort(400, description="Coordinates must be x_y_z numbers")
            if len(items) != 3 or not all(math.isfinite(v) for v in items):
                abort(400, description="Coordinates must be three finite x_y_z numbers")
            return items

        a = parse_coords(coords_a)
        b = parse_coords(coords_b)
        # MNI coordinates are millimeters. The existing table stores POINTZ
        # values with SRID 4326, but this uses geometry (not geography)
        # so ST_3DDWithin applies ordinary 3-D distance in numeric units.
        sql = text("""
            SELECT DISTINCT study_id
            FROM ns.coordinates
            WHERE ST_3DDWithin(
                geom, ST_SetSRID(ST_MakePoint(:ax, :ay, :az), 4326), :radius)
            EXCEPT
            SELECT DISTINCT study_id
            FROM ns.coordinates
            WHERE ST_3DDWithin(
                geom, ST_SetSRID(ST_MakePoint(:bx, :by, :bz), 4326), :radius)
        """)
        params = dict(zip(("ax", "ay", "az", "bx", "by", "bz"), a + b))
        params["radius"] = 6.0
        with get_engine().connect() as conn:
            ids = sorted(conn.execute(sql, params).scalars().all())
        return jsonify({"coordinate_a": a, "coordinate_b": b,
                        "radius_mm": 6, "count": len(ids), "study_ids": ids})

    @app.get("/test_db", endpoint="test_db")
    
    def test_db():
        eng = get_engine()
        payload = {"ok": False, "dialect": eng.dialect.name}

        try:
            with eng.begin() as conn:
                # Ensure we are in the correct schema
                conn.execute(text("SET search_path TO ns, public;"))
                payload["version"] = conn.exec_driver_sql("SELECT version()").scalar()

                # Counts
                payload["coordinates_count"] = conn.execute(text("SELECT COUNT(*) FROM ns.coordinates")).scalar()
                payload["metadata_count"] = conn.execute(text("SELECT COUNT(*) FROM ns.metadata")).scalar()
                payload["annotations_terms_count"] = conn.execute(text("SELECT COUNT(*) FROM ns.annotations_terms")).scalar()

                # Samples
                try:
                    rows = conn.execute(text(
                        "SELECT study_id, ST_X(geom) AS x, ST_Y(geom) AS y, ST_Z(geom) AS z FROM ns.coordinates LIMIT 3"
                    )).mappings().all()
                    payload["coordinates_sample"] = [dict(r) for r in rows]
                except Exception:
                    payload["coordinates_sample"] = []

                try:
                    # Select a few columns if they exist; otherwise select a generic subset
                    rows = conn.execute(text("SELECT * FROM ns.metadata LIMIT 3")).mappings().all()
                    payload["metadata_sample"] = [dict(r) for r in rows]
                except Exception:
                    payload["metadata_sample"] = []

                try:
                    rows = conn.execute(text(
                        "SELECT study_id, contrast_id, term, weight FROM ns.annotations_terms LIMIT 3"
                    )).mappings().all()
                    payload["annotations_terms_sample"] = [dict(r) for r in rows]
                except Exception:
                    payload["annotations_terms_sample"] = []

            payload["ok"] = True
            return jsonify(payload), 200

        except Exception as e:
            payload["error"] = str(e)
            return jsonify(payload), 500

    return app

# WSGI entry point (no __main__)
app = create_app()
