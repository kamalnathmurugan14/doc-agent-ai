from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/tools")
def list_tools(request: Request) -> dict:
    c = request.app.state.container
    return {"tools": [t.spec(c.settings) for t in c.registry.tools.values()]}
