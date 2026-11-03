#!/usr/bin/env python3
import http.server
import json
import os
import socketserver
from pathlib import Path
from urllib.parse import urlparse

PORT = 8767
DIRECTORY = "/Users/comedelavenne/AI-Excel-Agent/vc_exam_static"

class VCHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)
    
    def do_POST(self):
        if self.path == '/api/vc/tutor':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                question = data.get('question', '')
                # Use vc_tutor
                import sys
                sys.path.insert(0, '/Users/comedelavenne/AI-Excel-Agent')
                from vc_tutor import VCTutor
                tutor = VCTutor()
                answer = tutor.tutor_explain(question)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'answer': answer}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'answer': f'Error: {e}'}).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, *args):
        pass

os.chdir(DIRECTORY)
with socketserver.TCPServer(("127.0.0.1", PORT), VCHandler) as httpd:
    print(f"VC Exam Hub running on http://127.0.0.1:{PORT}")
    httpd.serve_forever()
