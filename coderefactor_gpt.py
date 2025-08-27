import argparse
import logging
import ast
import os
import sys
import json
import time
from pathlib import Path
from typing import Optional, Dict
from tenacity import retry, stop_after_attempt, wait_fixed

from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain_core.runnables import RunnableSequence

from rich.logging import RichHandler
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

import random
from package_utils import check_and_install_dependencies

# Set up rich logging for modern, colorful, enhanced logs
FORMAT = "%(message)s"
logging.basicConfig(
    level="INFO",
    format=FORMAT,
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False, markup=True)]
)
logger = logging.getLogger("rich")
console = Console()
global_analysis = None  # Global variable to store analysis

def read_logo() -> str:
    """Read the logo from logo.txt."""
    try:
        with open("logo.txt", 'r') as f:
            logo = f.read()
        return logo
    except Exception as e:
        logger.error(f"[red]❌ Error reading logo.txt: {str(e)}[/red]")
        return ""

def read_code_file(file_path: str) -> str:
    """Read the code from the given file path."""
    try:
        with open(file_path, 'r') as f:
            code = f.read()
        logger.info(f"[green]✅ Successfully read code file: {file_path}[/green]")
        return code
    except Exception as e:
        logger.error(f"[red]❌ Error reading file {file_path}: {str(e)}[/red]")
        sys.exit(1)

def check_syntax(code: str) -> bool:
    """Check for syntax errors using ast.parse."""
    try:
        ast.parse(code)
        logger.info("[green]✅ Syntax check passed: No syntax errors detected.[/green]")
        return False
    except SyntaxError as e:
        logger.error(f"[red]❌ Syntax error detected: {str(e)}[/red]")
        return str(e)

def check_runtime(code: str):
    """Attempt to execute the code in a restricted environment to detect runtime errors."""
    restricted_globals = {'__builtins__': {'__import__': __import__}}
    try:
        compiled = compile(code, '<string>', 'exec')
        exec(compiled, restricted_globals, {})
        logger.info("[green]✅ Runtime check passed: No runtime errors detected during execution.[/green]")
    except Exception as e:
        logger.error(f"[red]❌ Runtime error detected: {str(e)}[/red]")

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def semantic_analysis(code: str, llm_model: str, llm_provider: str, expert: bool = False, syntax_error: str = None, runtime_error: str = None) -> Optional[Dict]:
    """Use LangChain + LLM for semantic analysis."""
    global global_analysis
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        logger.error("[red]❌ OPENAI_API_KEY environment variable not set. Cannot perform semantic analysis.[/red]")
        return None

    llm = ChatOpenAI(model=llm_model, api_key=api_key, temperature=1) if llm_provider.lower() == "openai" else None
    if not llm:
        logger.error(f"[red]❌ Unsupported LLM provider: {llm_provider}[/red]")
        return None
        
    error_context = ""
    if syntax_error:
        error_context = f"\nSyntax Error found: {syntax_error}"
    if runtime_error:
        error_context += f"\nRuntime Error found: {runtime_error}"

    template = """You are a Professional Python code analyzer. Semantically analyze the following Python code. Look for logical errors, potential improvements, security issues, performance bottlenecks, and overall code quality. Don't give the improved code, you can give some improved code snippets, just discuss what code is doing and suggest improvements. Return the result in strict JSON format with a single 'analysis' field, e.g., {{\"analysis\": \"...\"}}:

        {error_context}

        ```python
        {code}
        ```"""
    if expert:
        template = """You are a Professional Python code analyzer in expert mode. Take your time to deeply analyze the following Python code for logical errors, potential improvements, security issues, performance bottlenecks, and overall code quality, with a primary focus on minimizing runtime and memory consumption as low as possible, no matter what. People chose expert mode because they want the best, professional, and robust code with the least memory and runtime consumption, as if in a coding competition. Discuss what the code is doing, suggest optimizations especially for performance, and provide detailed recommendations. Don't give the improved code, you can give some improved code snippets if you want but don't give in most cases. Return the result in strict JSON format with a single 'analysis' field, e.g., {{\"analysis\": \"...\"}}:

        {error_context}

        ```python
        {code}
        ```"""

    prompt = PromptTemplate(
        input_variables=["code", "error_context"],
        template=template
    )
    
    chain = RunnableSequence(prompt | llm)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True
    ) as progress:
        task = progress.add_task(description="Performing semantic analysis with LLM...", total=None)
        try:
            response = chain.invoke({"code": code, "error_context": error_context})
            response_text = response.content if hasattr(response, 'content') else str(response)
            try:
                result = json.loads(response_text)
                global_analysis = result.get("analysis", "")
                if not global_analysis:
                    raise ValueError("No 'analysis' field in JSON response")
                progress.update(task, completed=True)
                logger.info("[green]✅ Semantic analysis complete.[/green]")
                console.print("\n")
                console.print(Panel(global_analysis, title="Semantic Analysis Report", expand=False, border_style="bold blue"))
                return result
            except json.JSONDecodeError:
                logger.error("[red]❌ Failed to parse semantic analysis as JSON.[/red]")
                raise
            except ValueError as e:
                logger.error(f"[red]❌ Error in semantic analysis response: {str(e)}[/red]")
                raise
        except Exception as e:
            progress.update(task, completed=True)
            logger.error(f"[red]❌ Error during semantic analysis: {str(e)}[/red]")
            raise

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def basic_analysis_and_refactor(code: str, llm_model: str, llm_provider: str, syntax_error, runtime_error) -> Optional[Dict]:
    """Perform combined semantic analysis and basic refactoring in one LLM call."""
    global global_analysis
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        logger.error("[red]❌ OPENAI_API_KEY not set. Cannot perform basic analysis and refactor.[/red]")
        return None

    llm = ChatOpenAI(model=llm_model, api_key=api_key, temperature=1) if llm_provider.lower() == "openai" else None
    if not llm:
        logger.error(f"[red]❌ Unsupported LLM provider: {llm_provider}[/red]")
        return None

    error_context = ""
    if syntax_error:
        error_context = f"\nSyntax Error found: {syntax_error}"
    if runtime_error:
        error_context += f"\nRuntime Error found: {runtime_error}"

    prompt = PromptTemplate(
        input_variables=["code", "error_context"],
        template="""You are a Professional Python code analyzer. For the following Python code, perform semantic analysis (logical errors, improvements, security, performance, quality) and provide a beginner-friendly refactored version with minimal changes(but include the changes which are obvious), necessary imports, and light comments. Avoid overengineering or complex structures. You're main priority is to be FAST, be fast as possible even at analysis and writing the refactored code, don't waste too much tokens as you are in the BASIC mode. In this mode, you are preferably to be fast, don't check the code too deeply, if the code is small like 20-35 lines, you should be done in 5-10 SECONDS, if the code is too long like 100-200 lines, you should do analysis and refactor code in under a minute. Remember, people chose the BASIC mode because they want the results faster and good. So please try to be FASTER while doing your best in the code analysis. Return the result in strict JSON format with 'analysis' and 'code' fields, e.g., {{\"analysis\": \"...\", \"code\": \"...\"}}.

        {error_context}

        Example:
        Input:
        ```python
        time.sleep(2)
        print("Slept for 20 seconds.")
        ```

        Output:
        {{\"analysis\": \"The code has a logical error: the sleep duration (2 seconds) does not match the printed message (20 seconds). It also lacks the 'time' module import. The refactored code adds the import, fixes the message, and includes a light comment for clarity.\", \"code\": \"import time\\n\\ntime.sleep(2)  # replace the number with for how much time you want to sleep\\nprint(\\\"Slept for 2 seconds\\\")\"}}

        Now analyze and refactor this code:
        ```python
        {code}
        ```"""
    )
    
    chain = RunnableSequence(prompt | llm)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True
    ) as progress:
        task = progress.add_task(description="Performing basic analysis and refactoring with LLM...", total=None)
        try:
            response = chain.invoke({"code": code, "error_context": error_context})
            response_text = response.content if hasattr(response, 'content') else str(response)
            try:
                result = json.loads(response_text)
                if not all(key in result for key in ["analysis", "code"]):
                    raise ValueError("Missing 'analysis' or 'code' field in JSON response")
                global_analysis = result["analysis"]
                progress.update(task, completed=True)
                logger.info("[green]✅ Basic analysis and refactoring complete.[/green]")
                console.print("\n")
                console.print(Panel(result["analysis"], title="Basic Analysis Report", expand=False, border_style="bold blue"))
                return result
            except json.JSONDecodeError:
                logger.error("[red]❌ Failed to parse basic analysis and refactor as JSON.[/red]")
                raise
            except ValueError as e:
                logger.error(f"[red]❌ Error in basic analysis and refactor response: {str(e)}[/red]")
                raise
        except Exception as e:
            progress.update(task, completed=True)
            logger.error(f"[red]❌ Error during basic analysis and refactoring: {str(e)}[/red]")
            raise

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def refactor_code(code: str, output_path: str, llm_model: str, llm_provider: str, expert: bool = False):
    """Use LLM to refactor the code and save to output file (non-basic mode)."""
    global global_analysis
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        logger.error("[red]❌ OPENAI_API_KEY not set. Skipping refactor.[/red]")
        return

    llm = ChatOpenAI(model=llm_model, api_key=api_key, temperature=1) if llm_provider.lower() == "openai" else None
    if not llm:
        logger.error(f"[red]❌ Unsupported LLM provider: {llm_provider}[/red]")
        return

    template = """You are a Professional and Experienced Python code analyzer. Refactor the following Python code with the help of provided deep analysis by a code analysis expert to improve readability, fix any bugs, optimize performance, add detailed comments, and follow best practices. Avoid unnecessary use of logging module because they are used in production builds, people mostly use print as main logging, if the code is using the default print, use it else use logging if explicitly intimated. Keep the prior logic of the code as it is, don't add or delete your own part in the code, or don't change the way one function works(unless needed so or it has some complex calculation whose way need to be changed). Return the refactored code in strict JSON format with a single 'code' field, e.g., {{\"code\": \"...\"}}.

        Example:
        Input:
        ```python
        time.sleep(2)
        print("Slept for 20 seconds.")
        ```

        Output:
        {{\"code\": \"import time\\n\\ndef sleep_and_notify({{duration_seconds}}):\\n    \\\"\\\"\\\"Pauses the program for the specified number of seconds and then prints a notification.\\n\\n    Parameters:\\n    {{duration_seconds}} (int): The number of seconds to sleep.\\n\\n    Returns:\\n    None\\n    \\\"\\\"\\\" \\n    time.sleep({{duration_seconds}})\\n    print(f\\\"Slept for {{{{duration_seconds}}}} seconds.\\\")\\n\\n# Sleep for 2 seconds and notify\\nsleep_and_notify(2)\"}}

        Now refactor this code:
        ```python
        {code}
        ```
        Analysis: {analysis}"""
    if expert:
        template = """You are a Professional and Experienced Python code analyzer in expert mode. Refactor the following Python code with the help of provided deep analysis to improve readability, fix any bugs, and follow best practices, with a primary focus on optimizing for the lowest possible runtime and memory consumption, no matter what because you are in EXPERT mode, this mode allows the consumer to get the best version of their codes, like it makes them win in a competition. People chose expert mode because they wanted the best, professional, and robust code with the least memory and runtime consumption as if they were in a competition of it. Add detailed comments where necessary, but prioritize performance optimizations. Avoid unnecessary use of logging module because they are used in production builds, people mostly use print as main logging, if the code is using the default print, use it else use logging if explicitly intimated. Keep the prior logic of the code as it is, don't add or delete your own part in the code, or don't change the way one function works(unless needed for performance). Return the refactored code in strict JSON format with a single 'code' field, e.g., {{\"code\": \"...\"}}.

        Example:
        Input:
        ```python
        time.sleep(2)
        print("Slept for 20 seconds.")
        ```

        Output:
        {{\"code\": \"import time\\n\\ndef sleep_and_notify({{duration_seconds}}):\\n    \\\"\\\"\\\"Pauses the program for the specified number of seconds and then prints a notification.\\n\\n    Parameters:\\n    {{duration_seconds}} (int): The number of seconds to sleep.\\n\\n    Returns:\\n    None\\n    \\\"\\\"\\\" \\n    time.sleep({{duration_seconds}})\\n    print(f\\\"Slept for {{{{duration_seconds}}}} seconds.\\\")\\n\\n# Sleep for 2 seconds and notify\\nsleep_and_notify(2)\"}}

        Now refactor this code:
        ```python
        {code}
        ```
        Analysis: {analysis}"""

    prompt = PromptTemplate(
        input_variables=["code", "analysis"],
        template=template
    )
    
    chain = RunnableSequence(prompt | llm)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True
    ) as progress:
        task = progress.add_task(description="Refactoring code with LLM...", total=None)
        try:
            response = chain.invoke({"code": code, "analysis": global_analysis or "No prior analysis available"})
            response_text = response.content if hasattr(response, 'content') else str(response)
            try:
                refactored_data = json.loads(response_text)
                refactored_code = refactored_data.get("code", "")
                if not refactored_code:
                    raise ValueError("No 'code' field in JSON response")
                # Strip any markdown code fences
                refactored_code = refactored_code.strip()
                if refactored_code.startswith("```python"):
                    refactored_code = refactored_code[9:].rstrip("```").rstrip()
                # Check and install any missing dependencies
                if check_and_install_dependencies(refactored_code):
                    # Save the clean code
                    Path(output_path).write_text(refactored_code)
                    progress.update(task, completed=True)
                    logger.info(f"[green]✅ Refactored code saved to: {output_path}[/green]")
                else:
                    progress.update(task, completed=True)
                    logger.warning("[yellow]⚠️ Some dependencies could not be installed. The refactored code may not work correctly.[/yellow]")
            except json.JSONDecodeError:
                logger.error("[red]❌ Failed to parse refactored code as JSON.[/red]")
                raise
            except ValueError as e:
                logger.error(f"[red]❌ Error in refactored code response: {str(e)}[/red]")
                raise
        except Exception as e:
            progress.update(task, completed=True)
            logger.error(f"[red]❌ Error during code refactoring: {str(e)}[/red]")
            raise

def get_filename(path: str) -> str:
    """Get only the filename (remove directories and extension)."""
    filename = os.path.basename(path)
    name_without_ext, _ = os.path.splitext(filename)
    return name_without_ext

def get_random_color() -> str:
    """Get a random color for the logo panel."""
    logo_colors = ["red", "green", "magenta", "blue", "yellow", "bold cyan"]
    return random.choice(logo_colors)

class LogoArgumentParser(argparse.ArgumentParser):
    """Custom ArgumentParser that displays the logo in a Rich panel."""
    
    def __init__(self, *args, **kwargs):
        self.logo = kwargs.pop('logo', '')  # Extract logo from kwargs
        self.console = Console()
        # Remove logo from description but keep the rest
        if 'description' in kwargs:
            kwargs['description'] = kwargs['description'].replace(self.logo, '').strip()
        super().__init__(*args, **kwargs)
        
    def print_help(self, file=None):
        # Print logo in panel if available
        if self.logo:
            self.console.print(Panel(self.logo, title="CodeRefactorGPT", border_style=get_random_color(), expand=False))
            print()  # Add a blank line after the panel
        # Print normal help message
        super().print_help(file)

def main():
    global global_analysis
    start_time = time.time()  # Start timing
    logo = read_logo()
    
    # Create a custom formatter class that preserves formatting
    class CustomFormatter(argparse.HelpFormatter):
        def _fill_text(self, text, width, indent):
            return ''.join(indent + line if line.strip() else line
                         for line in text.splitlines(keepends=True))

    # Create the argument parser with the custom formatter
    parser = LogoArgumentParser(
        logo=logo,  # Pass logo separately
        description="AI Code Analyzer: Analyzes Python code for syntax, runtime, and semantic issues. Optionally refactors.",
        formatter_class=CustomFormatter,
        allow_abbrev=False
    )
    parser.add_argument('file_path', type=str, help="Path to the Python code file to analyze.")
    parser.add_argument('--refactor-output', type=str, help="Path to save refactored code (optional). If provided, refactoring will be performed.")
    parser.add_argument('--basic', action='store_true', help="Use basic refactoring mode for simple, beginner-friendly changes.")
    parser.add_argument('--expert', action='store_true', help="Use expert mode for deep analysis with focus on runtime and memory optimization.")
    parser.add_argument('--llm', type=str, default=None, help="LLM model to use (e.g., gpt-5, gpt-5-mini). Defaults to gpt-5 for normal/expert, gpt-5-mini for basic.")
    parser.add_argument('--llm-provider', type=str, default="openai", help="LLM provider (e.g., openai). Defaults to openai.")
    args = parser.parse_args()
    
    if args.basic and args.expert:
        logger.error("[red]❌ Cannot use --basic and --expert together.[/red]")
        sys.exit(1)
    
    # Set default LLM model based on mode
    if args.llm:
        llm_model = args.llm
    else:
        llm_model = "gpt-5-mini" if args.basic else "gpt-5"
    
    # Always display the logo at startup
    console.print(Panel(logo, title="CodeRefactorGPT", border_style=get_random_color(), expand=False))
    print()  # Add a blank line after the logo
    
    logger.info("[bold yellow]🚀 Starting code analysis...[/bold yellow]")
    if args.expert:
        logger.info("[bold magenta]🧠 Expert mode enabled: Deep analysis with focus on runtime and memory optimization.[/bold magenta]")
    elif args.basic:
        logger.info("[bold green]🏁 Basic mode enabled: Fast, simple analysis and beginner-friendly refactoring.[/bold green]")

    code = read_code_file(args.file_path)
    
    syntax_error = check_syntax(code)
    runtime_error = None
    
    if not syntax_error:
        try:
            check_runtime(code)
        except Exception as e:
            runtime_error = str(e)
    
    if args.basic and args.refactor_output:
        # Combined basic analysis and refactor
        result = basic_analysis_and_refactor(code, llm_model, args.llm_provider, syntax_error=syntax_error, runtime_error=runtime_error)
        if result and "code" in result:
            refactored_code = result["code"].strip()
            if refactored_code.startswith("```python"):
                refactored_code = refactored_code[9:].rstrip("```").rstrip()
            # Check and install any missing dependencies
            if check_and_install_dependencies(refactored_code):
                Path(args.refactor_output).write_text(refactored_code)
                logger.info(f"🤖 [yellow] Used Model: {llm_model}")
                logger.info(f"[bold green]✅ Refactored code saved to: {args.refactor_output}[/bold green]")
            else:
                logger.warning("[yellow]⚠️ Some dependencies could not be installed. The refactored code may not work correctly.[/yellow]")
    else:
        # Normal or expert semantic analysis
        result = semantic_analysis(code, llm_model, args.llm_provider, expert=args.expert, 
                                 syntax_error=syntax_error, runtime_error=runtime_error)
        # Normal or expert refactor if requested
        if args.refactor_output:
            refactor_code(code, args.refactor_output, llm_model, args.llm_provider, expert=args.expert)

    # Calculate and display elapsed time
    elapsed_time = time.time() - start_time
    minutes = int(elapsed_time // 60)
    seconds = elapsed_time % 60
    
    if minutes > 0:
        time_str = f"{minutes} minutes and {seconds:.2f} seconds"
    else:
        time_str = f"{seconds:.2f} seconds"
    
    file_name = f"{get_filename(args.file_path)}_report.txt"
    with open(file_name, 'w') as report_file:
        report_file.write(f"Analysis completed in {time_str}\n")
        if global_analysis:
            report_file.write(f"AI Semantic Analysis:\n{global_analysis}\n")

    logger.info("[bold yellow]🏁 Code analysis complete.[/bold yellow]")
    logger.info(f"[bold green]✅ Analysis report saved to: {file_name}")
    console.print(Panel(f"Total time taken: {time_str}", border_style="bold green"))

if __name__ == "__main__":
    main()