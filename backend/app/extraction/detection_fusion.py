from app.extraction.geometry import iou, containment


def fuse(native, visual):
    final = list(native)
    for proposal in visual:
        match = next((d for d in final if iou(d.bbox,proposal.bbox) > .82), None)
        if match:
            if proposal.method not in match.method:
                match.method += ' + ' + proposal.method
            match.confidence = min(.97, max(match.confidence,proposal.confidence)+.02)
        elif any(d.source and containment(proposal.bbox,d.bbox) > .96 for d in native):
            # Native image boundaries include valid white space, unlike CV foreground contours.
            continue
        else:
            if any(iou(d.bbox,proposal.bbox)>.18 for d in final):
                proposal.reasons.append('Detection engines disagree or regions overlap')
            final.append(proposal)
    # Deterministic row-major reading order; no box averaging.
    return sorted(final, key=lambda d: (round(d.bbox[1]/5), d.bbox[0], d.bbox[3]))
