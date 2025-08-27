import ast
import importlib.util
import subprocess
import sys
from rich.console import Console
from rich.prompt import Confirm
from rich.panel import Panel

console = Console()

def extract_imports(code: str) -> set:
    """Extract all import statements from the code."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                imports.add(name.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split('.')[0])
    return imports

def is_package_installed(package: str) -> bool:
    """Check if a package is installed."""
    try:
        spec = importlib.util.find_spec(package)
        return spec is not None
    except (ImportError, ValueError):
        return False

def get_builtin_modules() -> set:
    """Get a set of Python's built-in modules."""
    return set(sys.builtin_module_names) | {'os', 'sys', 'time', 'random', 'math', 'datetime', 'collections', 'json', 'logging', 'pathlib', 'typing', 'ast', 'argparse'}

def check_and_install_dependencies(code: str, progress=None) -> bool:
    """Check for missing dependencies in the code and install them if confirmed.
    
    Args:
        code (str): The Python code to check for dependencies
        progress (Progress, optional): Progress instance to pause during dependency check
    
    Returns:
        bool: True if all dependencies are satisfied (installed or skipped), False otherwise
    """
    if progress:
        # Pause the progress display during dependency check
        progress.stop()
    
    imports = extract_imports(code)
    builtin_modules = get_builtin_modules()
    missing_packages = {pkg for pkg in imports if pkg not in builtin_modules and not is_package_installed(pkg)}
    
    if not missing_packages:
        if progress:
            progress.start()
        return True
    
    # Clear any previous output and show dependencies panel
    console.print()
    console.print(Panel(
        "\n".join([f"  • {pkg}" for pkg in missing_packages]),
        title="📦 Additional Dependencies Required",
        border_style="yellow"
    ))
    console.print()
    
    if Confirm.ask("[bold yellow]Do you want to install these packages?[/bold yellow]"):
        console.print("\n[bold]Installing packages...[/bold]")
        for pkg in missing_packages:
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
                console.print(f"[green]✅ Successfully installed {pkg}[/green]")
            except subprocess.CalledProcessError as e:
                console.print(f"[red]❌ Failed to install {pkg}: {str(e)}[/red]")
                if progress:
                    progress.start()
                return False
        if progress:
            progress.start()
        return True
    
    if progress:
        progress.start()
    return False
