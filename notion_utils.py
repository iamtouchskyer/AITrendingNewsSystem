from notion_client import Client
import os

class NotionManager:
    def __init__(self, token, database_id):
        self.notion = Client(auth=token)
        self.database_id = database_id
        # 验证连接
        try:
            self.notion.databases.retrieve(self.database_id)
            print("Successfully connected to Notion database")
        except Exception as e:
            print(f"Failed to connect to Notion database: {str(e)}")
            raise

    def create_page(self, title, content, url):
        try:
            # 确保标题和内容是字符串
            title = str(title) if title else ''
            content = str(content) if content else ''
            
            # 打印调试信息
            print(f"Creating Notion page with title: {title}")
            print(f"URL: {url}")
            
            # 首先验证数据库访问权限
            self.notion.databases.retrieve(self.database_id)
            
            # 创建页面
            page = self.notion.pages.create(
                parent={"database_id": self.database_id},
                properties={
                    "Title": {
                        "title": [
                            {
                                "text": {
                                    "content": title
                                }
                            }
                        ]
                    },
                    "URL": {
                        "url": url
                    }
                },
                children=[
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {
                                        "content": content
                                    }
                                }
                            ]
                        }
                    }
                ]
            )
            print(f"Successfully created Notion page with ID: {page.id}")
            return page.id
        except Exception as e:
            print(f"Detailed Notion API error: {str(e)}")
            if hasattr(e, 'body'):
                print(f"Error body: {e.body}")
            if hasattr(e, 'status'):
                print(f"Error status: {e.status}")
            return None 