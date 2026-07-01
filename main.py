from fastapi import FastAPI, Request, File, UploadFile, BackgroundTasks, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
import os
import time
import json
import arxiv
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Cấu hình Gemini API
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel(model_name="gemini-2.5-flash")

# Cấu hình Supabase (Cloud Database)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Chưa cấu hình SUPABASE_URL và SUPABASE_KEY trong file .env")
    return create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="AI Researcher Platform")

os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)
os.makedirs("templates", exist_ok=True)
os.makedirs("uploads", exist_ok=True) # Tạm thời lưu video upload local để xử lý AI, data sẽ lưu cloud

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

import traceback
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    try:
        return templates.TemplateResponse(request=request, name="index.html")
    except Exception as e:
        print("ERROR IN ROOT ROUTE:", e)
        traceback.print_exc()
        raise e

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    try:
        supabase = get_supabase()
        
        file_path = f"uploads/{file.filename}"
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        print(f"Uploading {file.filename} to Gemini...")
        video_file = genai.upload_file(path=file_path)

        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)
        
        if video_file.state.name == "FAILED":
            raise ValueError("Gemini processing failed.")
            
        prompt = """
        Bạn là một AI Nghiên cứu Khoa học. Hãy phân tích video công nghệ này.
        Dựa trên nội dung video, hãy đề xuất MỘT ý tưởng đồ án khoa học/kỹ thuật.
        Trả về CỰC KỲ NGẮN GỌN dưới định dạng JSON:
        {"title": "Tên đồ án ngắn", "summary": "Tóm tắt ý tưởng 2 câu"}
        """
        response = model.generate_content([video_file, prompt])
        result_text = response.text.strip().removeprefix('```json').removesuffix('```').strip()
        ai_data = json.loads(result_text)
        
        # Lưu vào Supabase Cloud
        supabase.table('projects').insert({
            "title": ai_data['title'],
            "summary": ai_data['summary'],
            "source_video": file.filename
        }).execute()
        
        genai.delete_file(video_file.name)
        os.remove(file_path) # Xóa file local sau khi xong

        return {"status": "success", "message": "Đã tạo đồ án và lưu lên Đám Mây!", "project": ai_data}
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(ve)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Lỗi AI: {str(e)}"})

@app.post("/api/auto_learn")
async def auto_learn(field: str = Form(...)):
    try:
        supabase = get_supabase()
        
        import random
        
        # Dịch từ khóa tiếng Việt sang tiếng Anh vì arXiv là kho dữ liệu tiếng Anh
        field_en_prompt = f"Dịch từ khóa chuyên ngành sau sang tiếng Anh (CHỈ trả về từ khóa tiếng Anh, không thêm dấu câu hay giải thích): {field}"
        field_en_response = model.generate_content(field_en_prompt)
        field_en = field_en_response.text.strip().replace('"', '')

        query_string = f'all:"{field_en}"'
        client = arxiv.Client()
        
        # 1. Lấy 50 bài liên quan nhất và trộn ngẫu nhiên để không bị trùng lặp ở các lần bấm
        search_relevance = arxiv.Search(query=query_string, max_results=50)
        relevance_results = list(client.results(search_relevance))
        random.shuffle(relevance_results)
        
        # 2. Lấy 50 bài mới nhất và trộn ngẫu nhiên
        search_newest = arxiv.Search(query=query_string, max_results=50, sort_by=arxiv.SortCriterion.SubmittedDate)
        newest_results = list(client.results(search_newest))
        random.shuffle(newest_results)

        results_info = []
        articles_to_analyze = []
        seen_urls = set()

        # Hàm xử lý kết quả để tránh lặp code, lấy số lượng tối đa mỗi luồng
        def process_search_results(shuffled_results, limit=3):
            count = 0
            for r in shuffled_results:
                if count >= limit:
                    break
                    
                url = r.pdf_url
                if url in seen_urls:
                    continue
                
                title = r.title
                authors = ", ".join([a.name for a in r.authors])
                abstract = r.summary
                
                # Kiểm tra xem bài báo đã lưu trên Cloud chưa
                existing = supabase.table('knowledge').select('id').eq('url', url).execute()
                if len(existing.data) > 0:
                    continue

                seen_urls.add(url)
                articles_to_analyze.append({
                    "title": title,
                    "authors": authors,
                    "abstract": abstract,
                    "url": url
                })
                count += 1

        process_search_results(relevance_results, limit=3)
        process_search_results(newest_results, limit=2)

        # 3. Mở rộng tìm kiếm trên Google Scholar (bỏ qua một số bài ngẫu nhiên để lấy bài mới)
        try:
            from scholarly import scholarly
            search_scholar = scholarly.search_pubs(query_string)
            
            # Skip ngẫu nhiên 0 đến 5 bài đầu tiên để lấy bài khác nhau mỗi lần
            skip_count = random.randint(0, 5)
            for _ in range(skip_count):
                try:
                    next(search_scholar)
                except StopIteration:
                    break
                    
            for _ in range(1): # Lấy thêm 1 bài từ Google Scholar
                try:
                    pub = next(search_scholar)
                    url = pub.get('pub_url', pub.get('eprint_url', ''))
                    title = pub['bib'].get('title', '')
                    
                    if not url:
                        url = f"https://scholar.google.com/scholar?q={title}"
                        
                    if url not in seen_urls:
                        authors = ", ".join(pub['bib'].get('author', []))
                        abstract = pub['bib'].get('abstract', '')
                        
                        existing = supabase.table('knowledge').select('id').eq('url', url).execute()
                        if len(existing.data) == 0:
                            seen_urls.add(url)
                            articles_to_analyze.append({
                                "title": title,
                                "authors": authors,
                                "abstract": abstract,
                                "url": url
                            })
                except StopIteration:
                    break
        except Exception as e:
            print(f"Google Scholar error: {e}")

        if not articles_to_analyze:
            return {"status": "success", "message": "Không tìm thấy bài mới hoặc tất cả đã được học."}

        # AI Dịch thuật và Phân tích gộp
        prompt = "Bạn là một AI Nghiên cứu Khoa học và Dịch giả chuyên nghiệp. Dưới đây là dữ liệu các bài báo tiếng Anh (Tiêu đề và Tóm tắt). " \
                 "Yêu cầu: Hãy DỊCH CỰC KỲ CHI TIẾT VÀ ĐẦY ĐỦ toàn bộ nội dung sang tiếng Việt với văn phong học thuật. " \
                 "Bạn phải dịch trọn vẹn từng câu, không được cắt xén hay tóm tắt ngắn đi. " \
                 "Sau bản dịch toàn văn, hãy viết thêm 1 đoạn (2-3 câu) phân tích giá trị khoa học của bài báo này.\n" \
                 "YÊU CẦU BẮT BUỘC: Trả về ĐÚNG định dạng JSON mảng các object (không thêm text nào khác):\n" \
                 "[\n  {\"title_vi\": \"Tiêu đề tiếng Việt\", \"content_vi\": \"[Bản dịch toàn văn cực kỳ chi tiết]\", \"analysis\": \"Phân tích giá trị khoa học\"}\n]\n\n"
        
        for i, art in enumerate(articles_to_analyze):
            prompt += f"--- Bài {i+1} ---\nTitle: {art['title']}\nAbstract: {art['abstract']}\n\n"
        
        analysis_response = model.generate_content(prompt)
        result_text = analysis_response.text.strip().removeprefix('```json').removesuffix('```').strip()
        
        try:
            analyses = json.loads(result_text)
        except json.JSONDecodeError:
            # Fallback nếu JSON lỗi
            analyses = []

        for i, art in enumerate(articles_to_analyze):
            if i < len(analyses):
                title_vi = analyses[i].get("title_vi", art['title'])
                content_vi = analyses[i].get("content_vi", art['abstract'])
                analysis = analyses[i].get("analysis", "Đang xử lý phân tích...")
            else:
                title_vi = art['title']
                content_vi = art['abstract']
                analysis = "Lỗi trong quá trình dịch thuật."

            # Lưu lên Supabase Cloud
            supabase.table('knowledge').insert({
                "field": field,
                "title": title_vi,
                "authors": art['authors'],
                "content": content_vi,
                "analysis": analysis,
                "url": art['url'],
                "source": "arXiv"
            }).execute()
            
            results_info.append({"title": title_vi, "url": art['url']})

        return {"status": "success", "message": f"Đã dịch và học {len(results_info)} bài báo mới, lưu lên Đám Mây.", "learned_articles": results_info}
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(ve)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Lỗi: {str(e)}"})

@app.get("/api/projects")
async def get_projects():
    try:
        supabase = get_supabase()
        response = supabase.table('projects').select('*').order('id', desc=True).execute()
        return response.data
    except Exception as e:
        return []

@app.get("/api/knowledge")
async def get_knowledge():
    try:
        supabase = get_supabase()
        response = supabase.table('knowledge').select('*').order('id', desc=True).limit(10).execute()
        return response.data
    except Exception as e:
        return []

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

@app.delete("/api/knowledge")
async def clear_knowledge():
    try:
        supabase = get_supabase()
        # Delete all rows where id is not null (Supabase requires a filter for delete)
        supabase.table('knowledge').delete().neq('id', 0).execute()
        return {"status": "success", "message": "Đã xóa toàn bộ kiến thức cũ."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Lỗi: {str(e)}"})



