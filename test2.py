import arxiv

field = "Cơ điện tử"
query_string = f'all:"{field}" OR all:"cơ khí" OR all:"cơ điện tử" OR all:"tự động hóa" OR all:"công nghệ mới"'
search_relevance = arxiv.Search(query=query_string, max_results=50)
relevance_results = list(arxiv.Client().results(search_relevance))
print("Results found:", len(relevance_results))
