"""Fixed synthetic model outputs for public-source adapter tests, never gold scoring."""

# Exact fixture identities select canned provider responses; no language is parsed.
CAPTURES = {
    'National Day, October 1, 1983 Uploaded on March 5, 2009 Taken in October 1983 Chengde 承德 1983 承德 避暑山庄 Some rights reserved': ('1983-10-01','1983-10-31','month'),
    'Chengde street Taken on October 1, 1983 Uploaded on October 1, 2025 Licence': ('1983-10-01','1983-10-01','day'),
    'Chengde Mountain Resort 1983-10-01': ('1983-10-01','1983-10-01','day'),
    'Chengde Mountain Resort, photographed on 1983-10-01': ('1983-10-01','1983-10-01','day'),
    'Chengde Mountain Resort 2025-11-03': ('2025-11-03','2025-11-03','day'),
    'Chengde Mountain Resort, photographed on 2025-11-03': ('2025-11-03','2025-11-03','day'),
    'Chengde street 1983': ('1983-01-01','1983-12-31','year'),
    'Chengde 1983 street photograph': ('1983-01-01','1983-12-31','year'),
    'Chengde 1983 street photo': ('1983-01-01','1983-12-31','year'),
    'Chengde street 2025': ('2025-01-01','2025-12-31','year'),
    'Chengde street 2025-08-30': ('2025-08-30','2025-08-30','day'),
    'Chengde street 2025-11-03': ('2025-11-03','2025-11-03','day'),
    'Chengde street 1983-10-01': ('1983-10-01','1983-10-01','day'),
    'Chengde street 2025-08-30 Chengde street 2025-08-30': ('2025-08-30','2025-08-30','day'),
    '承德街景 1983': ('1983-01-01','1983-12-31','year'),
    '八十年代承德全景图。承德市档案馆供图': ('1980-01-01','1989-12-31','decade'),
    '2019年承德市全景。记者摄': ('2019-01-01','2019-12-31','year'),
    'Chengde street 1983 Chengde 1983 street photograph': ('1983-01-01','1983-12-31','year'),
    'Chengde 1983 street photo Chengde 1983 street photo': ('1983-01-01','1983-12-31','year'),
    'Chengde street 1983 Chengde street 1983': ('1983-01-01','1983-12-31','year'),
    '承德街景 1983 承德街景 1983': ('1983-01-01','1983-12-31','year'),
    'Taken in 1983': ('1983-01-01','1983-12-31','year'),
}


def proposal(records):
    assertions=[]
    for index,fields in enumerate(records):
        for field,text in fields.items():
            if text not in CAPTURES:
                continue
            start,end,precision=CAPTURES[text]
            assertions.append(dict(record=index,field=field,quote=text,char_start=0,char_end=len(text),
                role='capture',uncertain=False,start=start,end=end,precision=precision))
    return dict(complete=True,assertions=assertions,receipt={'response_id':'controlled-caption-response'})
