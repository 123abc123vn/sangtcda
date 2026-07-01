import arxiv

query_string = 'all:"mechatronics" OR all:"mechanical" OR all:"automation" OR all:"robotics"'
client = arxiv.Client()
search_relevance = arxiv.Search(query=query_string, max_results=50)
relevance_results = list(client.results(search_relevance))
print("Results found:", len(relevance_results))
