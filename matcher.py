from pathlib import Path
from typing import Dict, Any, Optional

from utils.json_store import (
    load_person,
    set_candidate_face,
    select_best_candidate,
    candidate_has_face,
    NO_IMAGE_TOKEN,
)
from face_recognize.face_compare import compare_faces
from utils.name_match import is_exact_name, name_similarity

FUZZY_MIN = 92


# Face metrics computation

def compute_missing_face_metrics(person_json: Path | str, src_image: str) -> None:
    """
    For each candidate without face metrics, run compare_faces(src_image, cand_img)
    and persist the 'face' field. Skips candidates with NO_IMAGE_TOKEN.
    """
    p = Path(person_json)
    data = load_person(p)
    candidates = data.get("candidates") or []

    for c in candidates:
        # Skip explicit "no image"
        if (c.get("photo_path") or "").strip() == NO_IMAGE_TOKEN:
            continue

        cand_img = c.get("photo_path") or c.get("image_file")
        url = c.get("profile_url")
        if not (cand_img and url):
            continue

        # Do not recompute if metrics already exist
        if candidate_has_face(p, url):
            continue

        try:
            fm = compare_faces(src_image, cand_img)
            set_candidate_face(p, url, fm)
            print(f"Compared to {cand_img}, score is {fm.get('sigmoid')}")
        except Exception:
            set_candidate_face(p, url, {"error": "no_face_metrics"})


# Best candidate selection

def pick_best_candidate(person_json: Path | str) -> Optional[Dict[str, Any]]:
    """
    Reloads JSON (after face metrics were potentially written) and returns
    the candidate dict with the highest face['sigmoid'], or None.
    """
    data = load_person(person_json)
    return select_best_candidate(data)


# Name classification

def classify_name_status(query_name: str, best_name: str, fuzzy_min: int = FUZZY_MIN) -> str:
    """
    Returns: 'matched' | 'Probable Match (Fuzzy Name)' | 'no_match'
    """
    if is_exact_name(query_name, best_name):
        return "matched"
    sim = name_similarity(query_name, best_name) or 0
    return "Probable Match (Fuzzy Name)" if sim >= fuzzy_min else "no_match"


# Orchestrator

def run_matcher(person_json: str | Path) -> Dict[str, Any]:
    """
    Compares the first source image to all candidates, picks the best by face,
    then applies name matching to set the final status.
    """
    p = Path(person_json)
    data = load_person(p)

    src_images = data.get("source_images") or []
    cands = data.get("candidates") or []
    if not src_images or not cands:
        return {
            "name": data.get("query_name"),
            "linkedin_url": "no_match",
            "image_similarity": 0.0,
            "match_status": "no_match",
        }

    src = src_images[0]

    # 1) compute missing face metrics and persist
    compute_missing_face_metrics(p, src)

    # 2) pick overall best by sigmoid
    best = pick_best_candidate(p)
    if not best:
        return {
            "name": data.get("query_name"),
            "linkedin_url": "no_match",
            "image_similarity": 0.0,
            "match_status": "no_match",
        }

    qname = data.get("query_name") or ""
    bname = best.get("name") or ""
    sig = float((best.get("face") or {}).get("sigmoid") or 0.0)

    # 3) classify by name (exact → matched; else fuzzy threshold)
    status = classify_name_status(qname, bname)

    return {
        "name": qname,
        "linkedin_url": best.get("profile_url"),
        "image_similarity": round(sig, 4),
        "match_status": status,
    }



def _cli():
    import argparse
    ap = argparse.ArgumentParser(description="Run matcher on one person JSON")
    ap.add_argument("json_path")
    args = ap.parse_args()
    _ = run_matcher(args.json_path)


if __name__ == "__main__":
    _cli()
