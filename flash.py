import ollama
import os
import time
import subprocess
import requests
import difflib
import json
import importlib.util
from typing import Dict, Any, Optional, List
from colorama import Fore, Style, init
from enum import Enum
import google.generativeai as genai
import openai
from dotenv import load_dotenv
from tinydb import TinyDB, Query

# Initialize environment and colorama
load_dotenv()
init(autoreset=True)

# Enum Definitions
class LogLevel(Enum):
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"
    DEBUG = "DEBUG"

class ModelProvider(Enum):
    OLLAMA = "ollama"
    OPENAI = "openai"
    GEMINI = "gemini"

# Core Components
class Logger:
    """Enhanced logging system with different levels and colors"""
    COLORS = {
        LogLevel.INFO: Fore.CYAN,
        LogLevel.SUCCESS: Fore.GREEN,
        LogLevel.WARNING: Fore.YELLOW,
        LogLevel.ERROR: Fore.RED,
        LogLevel.DEBUG: Fore.MAGENTA
    }

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.db = TinyDB('logs.json')

    def log(self, message: str, level: LogLevel = LogLevel.INFO):
        """Log formatted messages with timestamp and level"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        color = self.COLORS.get(level, Fore.WHITE)
        log_entry = f"[{timestamp}] [{level.value}] {self.agent_name}: {message}"
        print(f"{color}{log_entry}{Style.RESET_ALL}")
        self.db.insert({'timestamp': timestamp, 'level': level.value, 'message': message})

    def log_code_change(self, old_code: str, new_code: str, filename: str):
        """Log code changes in GitHub-style diff format"""
        diff = difflib.unified_diff(
            old_code.splitlines(),
            new_code.splitlines(),
            fromfile=f'a/{filename}',
            tofile=f'b/{filename}',
            lineterm=''
        )
        self.log(f"Code changes for {filename}:", LogLevel.INFO)
        for line in diff:
            if line.startswith('+'):
                print(f"{Fore.GREEN}{line}{Style.RESET_ALL}")
            elif line.startswith('-'):
                print(f"{Fore.RED}{line}{Style.RESET_ALL}")
            else:
                print(line)

class DatabaseManager:
    """Handles database configuration and migrations using NeDB"""
    def __init__(self):
        self.logger = Logger("DBManager")
        self.config_path = 'db_config.json'
        self.migrations_dir = 'migrations'
        self._initialize_db()

    def _initialize_db(self):
        """Initialize database configuration"""
        if not os.path.exists(self.config_path):
            self._create_initial_config()
        self.db = TinyDB(self.config_path)
        os.makedirs(self.migrations_dir, exist_ok=True)

    def _create_initial_config(self):
        """Create initial database configuration"""
        default_config = {
            "database": "project_db.json",
            "last_migration": "0000_initial",
            "migrations": []
        }
        with open(self.config_path, 'w') as f:
            json.dump(default_config, f, indent=2)
        self.logger.log("Created initial database config", LogLevel.SUCCESS)

    def apply_migrations(self):
        """Apply pending database migrations"""
        config = self.db.all()[0]
        applied = config['migrations']
        migration_files = sorted(os.listdir(self.migrations_dir))
        
        for migration in migration_files:
            if migration not in applied:
                self._run_migration(migration)
                self.db.update({'migrations': applied + [migration]})

    def _run_migration(self, filename: str):
        """Execute a migration file"""
        try:
            module_path = os.path.join(self.migrations_dir, filename)
            spec = importlib.util.spec_from_file_location(filename[:-3], module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.up()
            self.logger.log(f"Applied migration: {filename}", LogLevel.SUCCESS)
        except Exception as e:
            self.logger.log(f"Migration failed: {filename} - {str(e)}", LogLevel.ERROR)
            raise

class ConsoleUI:
    """Interactive console user interface with menu system"""
    def show_menu(self, title: str, options: List[str]) -> List[int]:
        """Display a numbered menu and return selected indices"""
        print(f"\n{Fore.CYAN}=== {title} ==={Style.RESET_ALL}")
        for i, option in enumerate(options, 1):
            print(f"{Fore.YELLOW}{i}. {option}{Style.RESET_ALL}")
        selections = input(f"\n{Fore.GREEN}Enter selections (comma-separated): {Style.RESET_ALL}")
        return [int(s.strip()) - 1 for s in selections.split(',')]

    def show_diff(self, diff: List[str]):
        """Display diff output with colors"""
        print(f"\n{Fore.CYAN}=== Code Changes ==={Style.RESET_ALL}")
        for line in diff:
            if line.startswith('+'):
                print(Fore.GREEN + line + Style.RESET_ALL)
            elif line.startswith('-'):
                print(Fore.RED + line + Style.RESET_ALL)
            else:
                print(line)

    def confirm_action(self, question: str) -> bool:
        """Get user confirmation for critical actions"""
        response = input(f"{Fore.YELLOW}{question} (y/n): {Style.RESET_ALL}")
        return response.lower() == 'y'

# AI Model Components
class ModelConfig:
    """Configuration class for AI models"""
    def __init__(self, provider: ModelProvider, model_name: str, 
                 api_key: str = None, base_url: str = None):
        self.provider = provider
        self.model_name = model_name
        self.api_key = api_key or os.getenv(f"{provider.name}_API_KEY")
        self.base_url = base_url

class AIModel:
    """Wrapper class for different AI models"""
    def __init__(self, config: ModelConfig):
        self.config = config
        self.logger = Logger("AIModel")
        self._initialize_provider()

    def _initialize_provider(self):
        """Initialize provider-specific configurations"""
        if self.config.provider == ModelProvider.GEMINI:
            genai.configure(api_key=self.config.api_key)
        elif self.config.provider == ModelProvider.OPENAI:
            openai.api_key = self.config.api_key

    def generate(self, prompt: str, system_prompt: str) -> str:
        """Generate response from AI model"""
        try:
            start_time = time.time()
            self.logger.log(f"Generating response with {self.config.model_name}", LogLevel.INFO)
            
            if self.config.provider == ModelProvider.OLLAMA:
                response = ollama.chat(
                    model=self.config.model_name,
                    messages=[{"role": "system", "content": system_prompt},
                              {"role": "user", "content": prompt}]
                )
                content = response['message']['content']
            elif self.config.provider == ModelProvider.OPENAI:
                response = openai.ChatCompletion.create(
                    model=self.config.model_name,
                    messages=[{"role": "system", "content": system_prompt},
                              {"role": "user", "content": prompt}]
                )
                content = response.choices[0].message['content']
            elif self.config.provider == ModelProvider.GEMINI:
                model = genai.GenerativeModel(self.config.model_name)
                response = model.generate_content(f"SYSTEM: {system_prompt}\nUSER: {prompt}")
                content = response.text.replace("**", "")

            self.logger.log(f"Generation completed in {time.time()-start_time:.2f}s", LogLevel.SUCCESS)
            return content
        except Exception as e:
            self.logger.log(f"Generation failed: {str(e)}", LogLevel.ERROR)
            raise

# Agent Classes
class BaseAgent:
    """Base class for all agents"""
    def __init__(self, role: str, model_config: ModelConfig):
        self.role = role
        self.model = AIModel(model_config)
        self.logger = Logger(role)
        self.db = DatabaseManager()
        self.ui = ConsoleUI()

    def _run_command(self, command: str) -> str:
        """Execute shell commands with logging"""
        self.logger.log(f"Executing command: {command}", LogLevel.DEBUG)
        try:
            result = subprocess.run(command, shell=True, check=True, 
                                  capture_output=True, text=True)
            return result.stdout
        except subprocess.CalledProcessError as e:
            self.logger.log(f"Command failed: {e.stderr}", LogLevel.ERROR)
            return None

class ProjectManager(BaseAgent):
    """Agent for project planning and management"""
    def create_project_plan(self, user_request: str) -> Dict[str, Any]:
        """Generate project structure and tasks with AI-generated name"""
        # Generate project name
        project_name = self._generate_project_name(user_request)
        
        # Generate project structure
        structure_prompt = f"""Create project structure for: {user_request}
        Project name: {project_name}
        Include:
        - Backend structure
        - Frontend components
        - Database setup
        - Deployment config
        Format your response with:
        PROJECT_NAME: {project_name}
        TASKS: comma,separated,tasks
        FILE: path/to/file
        ```code
        content
        ```"""
        
        response = self.model.generate(
            prompt=structure_prompt,
            system_prompt="You are a senior project manager. Create comprehensive project plans."
        )
        
        return self._parse_response(response, project_name)

    def _generate_project_name(self, user_request: str) -> str:
        """Generate creative technical project name using AI"""
        name_prompt = f"""Generate a technical project name based on: {user_request}
        Rules:
        1. Use 2-4 words
        2. Include tech-related terms
        3. Make it memorable
        4. Use camelCase formatting
        5. Avoid special characters"""
        
        try:
            raw_name = self.model.generate(
                prompt=name_prompt,
                system_prompt="You are a technical branding expert. Generate project names."
            ).strip()
            
            # Sanitize the name
            sanitized = raw_name.split('\n')[0].split(':')[-1].strip()
            sanitized = sanitized.replace(' ', '_').replace('-', '_')[:30]
            sanitized = sanitized.strip('_')  # إزالة الشرطات الطرفية
            if not sanitized:
                raise ValueError("Empty project name generated")
            
            return sanitized
            
        except Exception as e:
            self.logger.log(f"Name generation failed, using fallback name: {str(e)}", LogLevel.WARNING)
            return self._generate_fallback_name(user_request)

    def _generate_fallback_name(self, user_request: str) -> str:
        """Generate fallback project name"""
        clean_request = user_request[:20].lower().replace(' ', '_') if user_request else "project"
        clean_request = clean_request.strip('_') or "project"

        timestamp = str(int(time.time()))[-6:]
        return f"Project_{clean_request}_{timestamp}"

    def _parse_response(self, response: str, project_name: str) -> Dict[str, Any]:
        """Parse AI response into structured data with project name"""
        tasks = []
        files = {}
        current_file = None
        
        for line in response.split('\n'):
            line = line.strip()
            if line.startswith('PROJECT_NAME:'):
                # تحديث اسم المشروع من الاستجابة إذا وجد
                new_name = line.split('PROJECT_NAME:')[1].strip()[:30]
                if new_name:
                    project_name = new_name
            elif line.startswith('TASKS:'):
                tasks = [t.strip() for t in line.split('TASKS:')[1].split(',')]
            elif line.startswith('FILE:'):
                current_file = line.split('FILE:')[1].strip()
            elif line.startswith('```'):
                current_file = None
            elif current_file:
                files[current_file] = files.get(current_file, []) + [line]
        if not project_name:
            project_name = f"project_{int(time.time())}"
        
        return {
        "project_name": project_name,
        "tasks": tasks,
        "project_structure": {k: '\n'.join(v) for k, v in files.items()}
        }

# Fixed DeveloperAgent with code extraction
class DeveloperAgent(BaseAgent):
    """Agent for code generation with automatic reviews"""
    def generate_code(self, task: str, context: Dict[str, Any]) -> Dict[str, str]:
        """Generate and review code artifacts"""
        prompt = f"""Write production code for: {task}
        Context: {json.dumps(context, indent=2)}
        Include: Proper error handling, comments, and tests.
        Format: FILE: path/to/file\n```code\ncontent\n```"""
        
        response = self.model.generate(
            prompt=prompt,
            system_prompt="You are a senior developer. Write clean, maintainable code."
        )
        new_code = self._extract_code(response)
        existing_code = {f: self._get_existing_code(f) for f in new_code.keys()}
        
        if CodeReviewer().review_changes(new_code, existing_code):
            return new_code
        return {}

    def _extract_code(self, response: str) -> Dict[str, str]:
        """Extract code blocks from model response"""
        files = {}
        current_file = None
        
        for line in response.split('\n'):
            if line.startswith('FILE:'):
                current_file = line.split('FILE:')[1].strip()
                files[current_file] = []
            elif line.startswith('```'):
                continue
            elif current_file:
                files[current_file].append(line)
        
        return {k: '\n'.join(v).strip() for k, v in files.items() if v}

    def _get_existing_code(self, filename: str) -> str:
        """Check for existing code versions"""
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                return f.read()
        return ""

# Enhanced DevOpsAgent with project folder support
class DevOpsAgent(BaseAgent):
    def deploy_project(self, project_data: Dict[str, Any]):
        """Secure deployment pipeline"""
        try:
            project_dir = project_data.get('project_name', 'new_project').strip()
            
            # التحقق من صحة اسم المجلد
            if not project_dir:
                project_dir = "new_project"
                self.logger.log("Using default project name 'new_project'", LogLevel.WARNING)
                
            # إنشاء المسار بشكل آمن
            full_path = os.path.abspath(os.path.normpath(project_dir))
            os.makedirs(full_path, exist_ok=True)
            
            self._write_project_files(full_path, project_data.get('code', {}))
            self.logger.log(f"Project deployed to {full_path}", LogLevel.SUCCESS)
            
        except Exception as e:
            self.logger.log(f"Deployment failed: {str(e)}", LogLevel.ERROR)
            raise

    def _write_project_files(self, project_dir: str, code_artifacts: Dict[str, str]):
        """Write files to project directory"""
        for file_path, content in code_artifacts.items():
            full_path = os.path.join(project_dir, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w') as f:
                f.write(content)
            self.logger.log(f"Created file: {file_path}", LogLevel.INFO)

class SecurityManager:
    """Handles security configurations and checks"""
    def __init__(self):
        self.logger = Logger("SecurityManager")

    def add_security_deps(self, project_type: str):
        """Add security dependencies based on project type"""
        deps = {
            'node': ['helmet', 'express-validator'],
            'python': ['bandit', 'safety']
        }.get(project_type, [])
        
        if deps:
            self.logger.log(f"Adding security dependencies: {', '.join(deps)}", LogLevel.INFO)

    def create_env_template(self):
        """Create secure environment template"""
        template = """# SECURE ENVIRONMENT CONFIG
DB_HOST=your_host
DB_PASS=your_strong_password
API_KEY=your_secure_key"""
        with open('.env.example', 'w') as f:
            f.write(template)
        self.logger.log("Created secure .env template", LogLevel.SUCCESS)

class CodeReviewer:
    """Handles automatic code reviews and change approval"""
    def __init__(self):
        self.ui = ConsoleUI()

    def review_changes(self, code_artifacts: Dict[str, str], existing_code: Dict[str, str]) -> bool:
        """Conduct interactive code review for all files"""
        all_diffs = []
        for filename, new_code in code_artifacts.items():
            old_code = existing_code.get(filename, "")
            diff = difflib.unified_diff(
                old_code.splitlines(),
                new_code.splitlines(),
                fromfile=f'a/{filename}',
                tofile=f'b/{filename}',
                lineterm=''
            )
            all_diffs.extend(diff)
        
        print(f"\n{Fore.CYAN}=== All Code Changes ==={Style.RESET_ALL}")
        for line in all_diffs:
            if line.startswith('+'):
                print(Fore.GREEN + line + Style.RESET_ALL)
            elif line.startswith('-'):
                print(Fore.RED + line + Style.RESET_ALL)
            else:
                print(line)
        
        return self.ui.confirm_action("Approve all changes?")

# Orchestration System
class Orchestrator:
    """Main orchestration controller"""
    def __init__(self, agents_config: Dict[str, ModelConfig]):
        self.agents = self._initialize_agents(agents_config)
        self.ui = ConsoleUI()
        self.logger = Logger("Orchestrator")

    def _initialize_agents(self, configs: Dict[str, ModelConfig]) -> Dict[str, BaseAgent]:
        """Initialize all agents"""
        return {
            'project_manager': ProjectManager("ProjectManager", configs['project_manager']),
            'developer': DeveloperAgent("Developer", configs['developer']),
            'devops': DevOpsAgent("DevOps", configs['devops'])
        }

    def execute_pipeline(self, user_request: str):
        """Execute full project creation pipeline"""
        try:
            # Select project features
            enhancements = [
                "Database Integration",
                "REST API Support",
                "User Authentication",
                "Automated Testing"
            ]
            selected = self.ui.show_menu("Project Features", enhancements)
            
            # Create project plan
            project_plan = self.agents['project_manager'].create_project_plan(user_request)
            
            # Generate code
            code_artifacts = {}
            for task in project_plan['tasks']:
                code_artifacts.update(self.agents['developer'].generate_code(task, project_plan))


            if not project_plan.get('project_name'):
                raise ValueError("Project name is missing in project plan")
            

            # Deploy project
            self.agents['devops'].deploy_project({
                'code': code_artifacts,
                'project_name': project_plan['project_name'],
                'enhancements': [enhancements[i] for i in selected]
            })
        except Exception as e:
            self.logger.log(f"Pipeline failed: {str(e)}", LogLevel.ERROR)
            raise

# Main Execution
if __name__ == "__main__":
    AGENT_CONFIGS = {
        'project_manager': ModelConfig(
            provider=ModelProvider.GEMINI,
            model_name="gemini-2.0-flash-exp",
            api_key=os.getenv("GEMINI_API_KEY")
        ),
        'developer': ModelConfig(
            provider=ModelProvider.GEMINI,
            model_name="gemini-2.0-flash-exp",
            api_key=os.getenv("GEMINI_API_KEY")
        ),
        'devops': ModelConfig(
            provider=ModelProvider.GEMINI,
            model_name="gemini-2.0-flash-exp",
            api_key=os.getenv("GEMINI_API_KEY")
        )
    }

    # Initialize system
    orchestrator = Orchestrator(AGENT_CONFIGS)
    ui = ConsoleUI()

    # Main loop
    while True:
        action = ui.show_menu("Main Menu", [
            "Create New Project",
            "Run Development Server",
            "Apply Database Migrations",
            "Exit System"
        ])
        
        if action == [0]:
            user_request = input(f"{Fore.GREEN}Enter project description: {Style.RESET_ALL}")
            orchestrator.execute_pipeline(user_request)
        elif action == [1]:
            subprocess.run("npm run dev", shell=True)
        elif action == [2]:
            DatabaseManager().apply_migrations()
        elif action == [3]:
            print(f"{Fore.CYAN}Exiting system...{Style.RESET_ALL}")
            break