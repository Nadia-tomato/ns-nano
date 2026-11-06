# app.py
from flask import Flask, jsonify, abort, send_file
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

def create_app():
    app = Flask(__name__)

    @app.get("/", endpoint="health")
    def health():
        return "<p>Server working!</p>"

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
            WHERE term = :a AND weight > 0
            EXCEPT
            SELECT DISTINCT study_id
            FROM ns.annotations_terms
            WHERE term = :b AND weight > 0
        """)
        with get_engine().connect() as conn:
            ids = sorted(conn.execute(sql, {"a": a, "b": b}).scalars().all())
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
