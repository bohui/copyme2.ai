"""Geographic identity without changing source labels or administrative levels."""
import re
import unicodedata


def geographic_label(value):
    label = ' '.join(unicodedata.normalize('NFKC', str(value)).casefold().split())
    # Only the optional province/city suffix is equivalent. County, district
    # and town names remain distinct, as do their full containing hierarchies.
    return re.sub(r'([\u3400-\u9fff])[市省]$', r'\1', label)


def place_path(place, *, normalized=False):
    labels = [label for label in place.get('hierarchy', [])
              if geographic_label(label) not in {'earth', '地球'}]
    leaf = place.get('place', '')
    if labels and geographic_label(labels[-1]) == geographic_label(leaf):
        labels[-1] = leaf
    else:
        labels.append(leaf)
    return tuple(map(geographic_label, labels)) if normalized else labels


def place_identity(place):
    return place.get('granularity'), place_path(place, normalized=True)
