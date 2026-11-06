


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
