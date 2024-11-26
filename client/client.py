import socket
import argparse
import threading
import re
from urllib.parse import urlparse, urlsplit, urlencode

# Constants
BUFFER_SIZE = 4096
SOCKET_TIMEOUT = 5
LOCAL_PORT = 8000

class HTTPResponse:
    def __init__(self, raw_response):
        self.raw_response = raw_response
        self.headers = {}
        self.body = ''
        self.status_code = None
        self.parse_response()

    def parse_response(self):
        try:
            # Split headers and body
            headers_raw, self.body = self.raw_response.split('\r\n\r\n', 1)
            headers_lines = headers_raw.split('\r\n')
            
            # Parse status line
            status_line = headers_lines[0]
            self.status_code = int(status_line.split()[1])
            
            # Parse headers
            for line in headers_lines[1:]:
                if ': ' in line:
                    key, value = line.split(': ', 1)
                    self.headers[key.lower()] = value
        except Exception as e:
            print(f"Error parsing response: {e}")
            self.status_code = 500

class URLParser:
    def __init__(self, url):
        self.original_url = url
        self.parse_url()

    def parse_url(self):
        # Parse the URL
        parsed = urlparse(self.original_url)
        
        # Set default port based on scheme
        default_port = 443 if parsed.scheme == 'https' else 80
        
        self.scheme = parsed.scheme or 'http'
        self.hostname = parsed.hostname or 'localhost'
        self.port = parsed.port or default_port
        self.path = parsed.path or '/'
        
        # Remove leading slash from path for request
        self.request_path = self.path[1:] if self.path.startswith('/') else self.path
        
        # If path is empty or just /, use index.html
        if not self.request_path or self.request_path == '/':
            self.request_path = 'index.html'

def create_local_response(content):
    """Create HTTP response for local server"""
    headers = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html\r\n"
        f"Content-Length: {len(content)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    return headers.encode() + content.encode()

def handle_local_client(client_socket, html_content):
    """Handle incoming connections to local server"""
    try:
        # Receive the HTTP request (we'll ignore its contents)
        client_socket.recv(BUFFER_SIZE)
        
        # Send the stored HTML content
        response = create_local_response(html_content)
        client_socket.send(response)
    except Exception as e:
        print(f"Error handling client: {e}")
    finally:
        client_socket.close()

def start_local_server(html_content):
    """Start a basic HTTP server using sockets"""
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind(('localhost', LOCAL_PORT))
        server_socket.listen(1)
        print(f"\nLocal server started at http://localhost:{LOCAL_PORT}")
        
        while True:
            client_socket, _ = server_socket.accept()
            client_thread = threading.Thread(
                target=handle_local_client,
                args=(client_socket, html_content)
            )
            client_thread.daemon = True
            client_thread.start()
    except Exception as e:
        print(f"Server error: {e}")
    finally:
        server_socket.close()

def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description='Simple HTTP Client')
    parser.add_argument('url', type=str, help='URL to fetch (e.g., http://localhost:8080/index.html)')
    parser.add_argument('--method', type=str, default='GET', choices=['GET', 'PUT', 'POST'],
                       help='HTTP method (default: GET)')
    parser.add_argument('--data', type=str, help='Data to send with POST request (key1=value1&key2=value2)')
    parser.add_argument('--content-type', type=str, default='application/x-www-form-urlencoded',
                       help='Content type for POST request')
    args = parser.parse_args()

    try:
        # Parse the URL
        url_info = URLParser(args.url)
        
        # Print parsed information
        print(f"\nParsed URL information:")
        print(f"Hostname: {url_info.hostname}")
        print(f"Port: {url_info.port}")
        print(f"Path: {url_info.path}")
        print(f"Method: {args.method}\n")

        # Create client socket and connect to server
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((url_info.hostname, url_info.port))
        
        # Prepare request body for POST
        body = ""
        content_length = 0
        if args.method == 'POST' and args.data:
            body = args.data
            content_length = len(body)
        
        # Create HTTP request
        request = (
            f"{args.method} /{url_info.request_path} HTTP/1.1\r\n"
            f"Host: {url_info.hostname}:{url_info.port}\r\n"
            "User-Agent: Simple-Client\r\n"
            "Accept: */*\r\n"
        )
        
        # Add content-related headers for POST
        if args.method == 'POST' and args.data:
            request += f"Content-Type: {args.content_type}\r\n"
            request += f"Content-Length: {content_length}\r\n"
        
        request += "Connection: close\r\n\r\n"
        
        # Add body for POST
        if args.method == 'POST' and args.data:
            request += body
        
        print("Sending request...")
        # Send request
        client_socket.send(request.encode())
        client_socket.settimeout(SOCKET_TIMEOUT)
        
        # Receive response
        print("Waiting for response...")
        response_data = bytearray()
        try:
            while True:
                chunk = client_socket.recv(BUFFER_SIZE)
                if not chunk:
                    break
                response_data.extend(chunk)
        except socket.timeout:
            print("Connection timed out while receiving data")
        
        # Parse response
        response = HTTPResponse(response_data.decode('utf-8', errors='ignore'))
        
        # Check if response is HTML and status is 200
        if (response.status_code == 200 and 
            response.headers.get('content-type', '').startswith('text/html')):
            
            # Start local server in a separate thread
            server_thread = threading.Thread(
                target=start_local_server,
                args=(response.body,),
                daemon=True
            )
            server_thread.start()
            
            print(f"Received HTML content. View it at http://localhost:{LOCAL_PORT}")
            print("Press Ctrl+C to exit...")
            
            try:
                server_thread.join()
            except KeyboardInterrupt:
                print("\nShutting down...")
        else:
            print(f"Response Status: {response.status_code}")
            print("\nHeaders:")
            for key, value in response.headers.items():
                print(f"{key}: {value}")
            print("\nBody:")
            print(response.body)
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'client_socket' in locals():
            client_socket.close()

if __name__ == "__main__":
    main()