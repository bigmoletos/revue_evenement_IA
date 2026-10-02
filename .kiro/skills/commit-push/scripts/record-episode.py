#!/usr/bin/env python
"""record-episode.py

Enregistre un episode dans la base Memgraph Base_Project (bolt://localhost:7688).

Schema du noeud : Episode(type, content, timestamp, palier, source)

Degradation gracieuse : si le driver neo4j est absent ou si Memgraph ne repond
pas, le script affiche un avertissement et sort avec le code 0 (ne bloque jamais
le skill commit-push appelant).

Usage :
    python record-episode.py --type commit \
                             --content "feat: ... (commit <hash>)" \
                             --palier 0 \
                             [--source commit-push] \
                             [--uri bolt://localhost:7688]
"""
import argparse
import sys
from datetime import datetime, timezone


def main() -> int:
    parser = argparse.ArgumentParser(description="Enregistre un episode dans Memgraph Base_Project")
    parser.add_argument("--type", required=True, help="Type d'episode (commit, decision, error, ...)")
    parser.add_argument("--content", required=True, help="Resume lisible de l'episode")
    parser.add_argument("--palier", type=int, default=0, help="Palier concerne (0 si hors palier)")
    parser.add_argument("--source", default="commit-push", help="Source de l'episode")
    parser.add_argument("--uri", default="bolt://localhost:7688", help="URI bolt de Base_Project")
    args = parser.parse_args()

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("[ATTENTION] driver neo4j absent, episode non enregistre")
        return 0

    try:
        driver = GraphDatabase.driver(args.uri)
        with driver.session() as session:
            session.run(
                "CREATE (e:Episode {type:$type, content:$content, "
                "timestamp:$ts, palier:$palier, source:$source})",
                type=args.type,
                content=args.content,
                ts=datetime.now(timezone.utc).isoformat(),
                palier=args.palier,
                source=args.source,
            )
        driver.close()
        print("[OK] Episode enregistre dans Base_Project (" + args.uri + ")")
    except Exception as ex:  # noqa: BLE001 - degradation gracieuse voulue
        print("[ATTENTION] Memgraph indisponible, episode non enregistre : " + str(ex))

    return 0


if __name__ == "__main__":
    sys.exit(main())
