import socket
import argparse
import os
import datetime
import time
import urllib.parse
import json
from pathlib import Path
import statistics
import threading

# Constants for storage
STORAGE_DIR = "post_data"
FORM_DATA_FILE = "form_submissions.json"
RAW_DATA_DIR = "raw_submissions"

response_times = []
response_times_lock = threading.Lock()

class ResponseTimeTracker:
    def __init__(self, method, uri):
        self.method = method
        self.uri = uri
        self.start_time = None
        self.end_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        response_time = (self.end_time - self.start_time) * 1000  # Convert to milliseconds
        
        with response_times_lock:
            response_times.append({
                'method': self.method,
                'uri': self.uri,
                'response_time': response_time,
                'timestamp': datetime.datetime.now().isoformat()
            })
        
        print(f"Request: {self.method} {self.uri}")
        print(f"Response Time: {response_time:.2f}ms")

def get_response_stats():
    """Get statistics about response times"""
    with response_times_lock:
        if not response_times:
            return "No requests processed yet."
        
        times = [r['response_time'] for r in response_times]
        method_times = {}
        
        # Group response times by method
        for r in response_times:
            method = r['method']
            if method not in method_times:
                method_times[method] = []
            method_times[method].append(r['response_time'])
        
        stats = {
            'total_requests': len(times),
            'average_response_time': statistics.mean(times),
            'median_response_time': statistics.median(times),
            'min_response_time': min(times),
            'max_response_time': max(times),
            'method_stats': {
                method: {
                    'count': len(method_times[method]),
                    'average': statistics.mean(method_times[method])
                }
                for method in method_times
            }
        }
        
        return stats
    
# Create necessary directories if they don't exist
Path(STORAGE_DIR).mkdir(exist_ok=True)
Path(os.path.join(STORAGE_DIR, RAW_DATA_DIR)).mkdir(exist_ok=True)

def store_form_data(form_data):
    """Store form data in JSON file"""
    file_path = os.path.join(STORAGE_DIR, FORM_DATA_FILE)
    
    # Load existing data or create empty list
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            data = json.load(f)
    else:
        data = []
    
    # Add timestamp and append new entry
    form_data['timestamp'] = datetime.datetime.now().isoformat()
    data.append(form_data)
    
    # Save updated data
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    return len(data)  # Return entry number

def store_raw_data(raw_data):
    """Store raw data in a file"""
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"raw_submission_{timestamp}.txt"
    file_path = os.path.join(STORAGE_DIR, RAW_DATA_DIR, filename)
    
    with open(file_path, 'w') as f:
        f.write(raw_data)
    
    return filename

def get_content_type(file_ext):
    """Return the appropriate content type based on file extension"""
    content_types = {
        '.html': 'text/html',
        '.htm': 'text/html',
        '.txt': 'text/plain',
        '.css': 'text/css',
        '.js': 'application/javascript',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif'
    }
    return content_types.get(file_ext.lower(), 'application/octet-stream')

def create_http_response(status_code, status_text, headers, body=None):
    """Create a properly formatted HTTP response"""
    response = f"HTTP/1.1 {status_code} {status_text}\r\n"
    
    # Add standard headers
    response += f"Date: {datetime.datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT')}\r\n"
    response += "Server: Simple_Server\r\n"
    
    # Add CORS headers
    response += "Access-Control-Allow-Origin: *\r\n"
    response += "Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS\r\n"
    response += "Access-Control-Allow-Headers: Content-Type\r\n"
    
    # Add custom headers
    for key, value in headers.items():
        response += f"{key}: {value}\r\n"
    
    # Add blank line to separate headers from body
    response += "\r\n"
    
    # Add body if exists
    if body is not None:
        response += body
    
    return response

def handle_get_request(request_uri):
    """Handle GET requests"""
    try:
        if not request_uri or request_uri == '/':
            request_uri = 'index.html'
        
        # Remove any query parameters
        request_uri = request_uri.split('?')[0]
        
        # Clean the path to prevent directory traversal
        request_uri = os.path.normpath(request_uri).lstrip('/')
        
        if os.path.exists(request_uri):
            file_stats = os.stat(request_uri)
            modified_time = time.strftime('%a, %d %b %Y %H:%M:%S GMT', 
                                        time.gmtime(file_stats.st_mtime))
            file_size = file_stats.st_size
            _, ext = os.path.splitext(request_uri)
            content_type = get_content_type(ext)

            with open(request_uri, 'rb') as f:
                content = f.read()

            headers = {
                'Content-Type': content_type,
                'Content-Length': str(file_size),
                'Last-Modified': modified_time,
                'Connection': 'close'
            }

            response_headers = create_http_response(200, 'OK', headers)
            return response_headers.encode() + content

        else:
            headers = {'Content-Type': 'text/plain', 'Connection': 'close'}
            response = create_http_response(404, 'Not Found', headers, 'File not found')
            return response.encode()

    except Exception as e:
        headers = {'Content-Type': 'text/plain', 'Connection': 'close'}
        response = create_http_response(500, 'Internal Server Error', headers, str(e))
        return response.encode()

def handle_put_request(request_uri, request):
    """Handle PUT requests with improved error handling"""
    try:
        # Validate request URI
        if not request_uri:
            headers = {'Content-Type': 'text/plain', 'Connection': 'close'}
            response = create_http_response(400, 'Bad Request', headers, 'Invalid file path')
            return response.encode()

        # Clean the path to prevent directory traversal
        try:
            # Ensure we're working with a relative path 
            safe_uri = os.path.normpath(request_uri).lstrip('/')
            
            # Prevent writing outside of current directory
            if safe_uri.startswith('..') or safe_uri.startswith('/'):
                headers = {'Content-Type': 'text/plain', 'Connection': 'close'}
                response = create_http_response(403, 'Forbidden', headers, 'Invalid file path')
                return response.encode()

            # Parse the request to get the body
            parts = request.split('\r\n\r\n', 1)
            if len(parts) != 2:
                raise ValueError("Invalid request format")
            
            _, body = parts

            # Create directories if they don't exist
            file_dir = os.path.dirname(safe_uri)
            if file_dir:
                os.makedirs(file_dir, exist_ok=True)

            # Write the content to the file
            with open(safe_uri, 'w') as f:
                f.write(body)
            
            headers = {
                'Content-Type': 'text/plain',
                'Content-Length': '0',
                'Connection': 'close'
            }
            
            response = create_http_response(201, 'Created', headers)
            return response.encode()
        
        except PermissionError:
            headers = {'Content-Type': 'text/plain', 'Connection': 'close'}
            response = create_http_response(403, 'Forbidden', headers, 'Permission denied')
            return response.encode()
        
        except OSError as e:
            print(f"OSError in PUT request: {e}")
            headers = {'Content-Type': 'text/plain', 'Connection': 'close'}
            response = create_http_response(500, 'Internal Server Error', headers, f'File error: {str(e)}')
            return response.encode()

    except Exception as e:
        print(f"Unexpected error in PUT request: {e}")
        headers = {'Content-Type': 'text/plain', 'Connection': 'close'}
        response = create_http_response(500, 'Internal Server Error', headers, str(e))
        return response.encode()

def handle_delete_request(request_uri):
    """Handle DELETE requests"""
    try:
        # Clean the path to prevent directory traversal
        request_uri = os.path.normpath(request_uri).lstrip('/')
        
        if not os.path.exists(request_uri):
            headers = {'Content-Type': 'text/plain', 'Connection': 'close'}
            response = create_http_response(404, 'Not Found', headers, 'File not found')
            return response.encode()
        
        # Delete the file
        os.remove(request_uri)
        
        headers = {
            'Content-Type': 'text/plain',
            'Content-Length': '0',
            'Connection': 'close'
        }
        
        response = create_http_response(200, 'OK', headers)
        return response.encode()
        
    except Exception as e:
        headers = {'Content-Type': 'text/plain', 'Connection': 'close'}
        response = create_http_response(500, 'Internal Server Error', headers, str(e))
        return response.encode()

def parse_post_data(request):
    """Parse POST request data based on Content-Type"""
    try:
        headers = {}
        content_type = ""
        
        # Split request into headers and body
        parts = request.split('\r\n\r\n', 1)
        if len(parts) != 2:
            raise ValueError("Invalid request format")
            
        header_section, body_section = parts
        header_lines = header_section.split('\r\n')
        
        # Parse headers
        for line in header_lines[1:]:  # Skip first line (request line)
            if ': ' in line:
                key, value = line.split(': ', 1)
                headers[key.lower()] = value
        
        content_type = headers.get('content-type', '')
        
        # Handle different content types
        if content_type == 'application/x-www-form-urlencoded':
            # Parse form data
            form_data = {}
            if body_section:
                pairs = body_section.split('&')
                for pair in pairs:
                    if '=' in pair:
                        key, value = pair.split('=', 1)
                        form_data[urllib.parse.unquote(key)] = urllib.parse.unquote(value)
            return 'form', form_data
        else:
            # Return raw body for other content types
            return 'raw', body_section
    except Exception as e:
        raise ValueError(f"Error parsing POST data: {str(e)}")

def handle_post_request(request):
    """Handle POST requests"""
    try:
        # Parse POST data
        data_type, post_data = parse_post_data(request)
        
        # Store data and get storage info
        if data_type == 'form':
            entry_number = store_form_data(post_data)
            response_body = (
                f"Form data stored successfully!\n"
                f"Entry number: {entry_number}\n"
                f"Stored in: {STORAGE_DIR}/{FORM_DATA_FILE}"
            )
        else:
            filename = store_raw_data(post_data)
            response_body = (
                f"Raw data stored successfully!\n"
                f"Stored in: {STORAGE_DIR}/{RAW_DATA_DIR}/{filename}"
            )
        
        headers = {
            'Content-Type': 'text/plain',
            'Content-Length': str(len(response_body)),
            'Connection': 'close'
        }
        
        response = create_http_response(200, 'OK', headers, response_body)
        return response.encode()
        
    except Exception as e:
        headers = {'Content-Type': 'text/plain', 'Connection': 'close'}
        response = create_http_response(500, 'Internal Server Error', headers, str(e))
        return response.encode()

def handle_options_request():
    """Handle OPTIONS request (CORS preflight)"""
    headers = {
        'Content-Type': 'text/plain',
        'Connection': 'close'
    }
    return create_http_response(200, 'OK', headers).encode()

def handle_stats_request():
    """Handle requests for server statistics"""
    try:
        stats = get_response_stats()
        response_body = json.dumps(stats, indent=2)
        
        headers = {
            'Content-Type': 'application/json',
            'Content-Length': str(len(response_body)),
            'Connection': 'close'
        }
        
        response = create_http_response(200, 'OK', headers, response_body)
        return response.encode()
        
    except Exception as e:
        headers = {'Content-Type': 'text/plain', 'Connection': 'close'}
        response = create_http_response(500, 'Internal Server Error', headers, str(e))
        return response.encode()
    

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("port", type=int, nargs='?', default=8080)
    args = parser.parse_args()
    PORT = args.port

    # Create socket and listen for client connections
    serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    serversocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    serversocket.bind(("localhost", PORT))
    serversocket.listen(1)
    print(f"HTTP server started, serving at port {PORT}")

    # Infinite loop to check if a client is connecting
    while True:
        clientsocket = None
        try:
            clientsocket, address = serversocket.accept()
            request = clientsocket.recv(4096).decode()

            if not request:
                continue

            # Parse request
            request_lines = request.split('\n')
            first_line = request_lines[0]
            method = first_line.split()[0]
            request_uri = first_line.split()[1][1:]  # remove leading /

            # Special endpoint for stats
            if request_uri == 'server-stats':
                response = handle_stats_request()
                clientsocket.send(response)
                continue

            # Handle different HTTP methods with response time tracking
            with ResponseTimeTracker(method.strip(), request_uri) as _:
                if method.strip() == 'OPTIONS':
                    response = handle_options_request()
                elif method.strip() == 'GET':
                    response = handle_get_request(request_uri)
                elif method.strip() == 'POST':
                    response = handle_post_request(request)
                elif method.strip() == 'PUT':
                    response = handle_put_request(request_uri, request)
                elif method.strip() == 'DELETE':
                    response = handle_delete_request(request_uri)
                else:
                    headers = {'Content-Type': 'text/plain', 'Connection': 'close'}
                    response = create_http_response(405, 'Method Not Allowed', headers, 'Method not supported')
                    response = response.encode()

                clientsocket.send(response)

        except Exception as e:
            print(f"Error: {e}")
            if clientsocket:
                try:
                    headers = {'Content-Type': 'text/plain', 'Connection': 'close'}
                    response = create_http_response(500, 'Internal Server Error', headers, str(e))
                    clientsocket.send(response.encode())
                except:
                    pass
        finally:
            if clientsocket:
                clientsocket.close()

if __name__ == "__main__":
    main()