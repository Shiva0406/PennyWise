from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select
from prometheus_fastapi_instrumentator import Instrumentator
from .database import Base, engine, get_db
from . import models, schemas
from .security import hash_password, verify_password, make_token, current_user
import os

app = FastAPI(title="Splitwise Lab API", version="1.0.0")
origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
Instrumentator().instrument(app).expose(app, endpoint="/metrics")
Base.metadata.create_all(bind=engine)

def member_required(db, group_id, user_id):
    row = db.scalar(select(models.GroupMember).where(models.GroupMember.group_id == group_id, models.GroupMember.user_id == user_id))
    if not row: raise HTTPException(403, "You are not a member of this group")

@app.get("/health")
def health(): return {"status": "ok"}

@app.post("/api/auth/register")
def register(data: schemas.RegisterIn, db: Session = Depends(get_db)):
    if db.scalar(select(models.User).where(models.User.email == data.email)):
        raise HTTPException(409, "Email already registered")
    user = models.User(name=data.name, email=data.email, password_hash=hash_password(data.password))
    db.add(user); db.commit(); db.refresh(user)
    return {"token": make_token(user.id), "user": {"id": user.id, "name": user.name, "email": user.email}}

@app.post("/api/auth/login")
def login(data: schemas.LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(models.User).where(models.User.email == data.email))
    if not user or not verify_password(data.password, user.password_hash): raise HTTPException(401, "Incorrect email or password")
    return {"token": make_token(user.id), "user": {"id": user.id, "name": user.name, "email": user.email}}

@app.get("/api/me")
def me(user=Depends(current_user)):
    return {"id": user.id, "name": user.name, "email": user.email}

@app.get("/api/groups")
def groups(db: Session = Depends(get_db), user=Depends(current_user)):
    memberships = db.scalars(select(models.GroupMember).where(models.GroupMember.user_id == user.id)).all()
    result = []
    for m in memberships:
        g = db.get(models.Group, m.group_id)
        if g: result.append({"id": g.id, "name": g.name, "member_count": len(g.members)})
    return result

@app.post("/api/groups")
def create_group(data: schemas.GroupIn, db: Session = Depends(get_db), user=Depends(current_user)):
    g = models.Group(name=data.name, created_by=user.id)
    db.add(g); db.flush()
    db.add(models.GroupMember(group_id=g.id, user_id=user.id))
    db.commit(); db.refresh(g)
    return {"id": g.id, "name": g.name, "member_count": 1}

@app.post("/api/groups/{group_id}/members")
def add_member(group_id: int, data: schemas.MemberIn, db: Session = Depends(get_db), user=Depends(current_user)):
    member_required(db, group_id, user.id)
    g = db.get(models.Group, group_id)
    target = db.scalar(select(models.User).where(models.User.email == data.email))
    if not target: raise HTTPException(404, "User must register before being added")
    exists = db.scalar(select(models.GroupMember).where(models.GroupMember.group_id == group_id, models.GroupMember.user_id == target.id))
    if not exists:
        db.add(models.GroupMember(group_id=group_id, user_id=target.id)); db.commit()
    return {"message": f"{target.name} is a group member"}

@app.get("/api/groups/{group_id}/members")
def members(group_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    member_required(db, group_id, user.id)
    rows = db.scalars(select(models.GroupMember).where(models.GroupMember.group_id == group_id)).all()
    return [{"id": (u := db.get(models.User, r.user_id)).id, "name": u.name, "email": u.email} for r in rows]

@app.post("/api/groups/{group_id}/expenses")
def add_expense(group_id: int, data: schemas.ExpenseIn, db: Session = Depends(get_db), user=Depends(current_user)):
    member_required(db, group_id, user.id)
    member_ids = {r.user_id for r in db.scalars(select(models.GroupMember).where(models.GroupMember.group_id == group_id)).all()}
    split_ids = set(data.split_between)
    if data.paid_by not in member_ids or not split_ids or not split_ids.issubset(member_ids):
        raise HTTPException(400, "Payer and split members must belong to this group")
    if abs(data.amount - round(data.amount, 2)) > 0.00001: raise HTTPException(400, "Use at most 2 decimal places")
    expense = models.Expense(group_id=group_id, paid_by=data.paid_by, description=data.description, amount=data.amount)
    db.add(expense); db.flush()
    share = round(data.amount / len(split_ids), 2)
    remaining = round(data.amount - share * (len(split_ids)-1), 2)
    for i, uid in enumerate(sorted(split_ids)):
        db.add(models.ExpenseSplit(expense_id=expense.id, user_id=uid, amount=remaining if i == len(split_ids)-1 else share))
    db.commit()
    return {"id": expense.id, "message": "Expense added"}

@app.get("/api/groups/{group_id}/expenses")
def expenses(group_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    member_required(db, group_id, user.id)
    rows = db.scalars(select(models.Expense).where(models.Expense.group_id == group_id).order_by(models.Expense.created_at.desc())).all()
    return [{"id": e.id, "description": e.description, "amount": e.amount, "paid_by": e.paid_by, "payer_name": db.get(models.User, e.paid_by).name, "created_at": e.created_at.isoformat() if e.created_at else None} for e in rows]

@app.get("/api/groups/{group_id}/balances")
def balances(group_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    member_required(db, group_id, user.id)
    member_rows = db.scalars(select(models.GroupMember).where(models.GroupMember.group_id == group_id)).all()
    ids = [m.user_id for m in member_rows]
    net = {uid: 0.0 for uid in ids}
    exp_rows = db.scalars(select(models.Expense).where(models.Expense.group_id == group_id)).all()
    for e in exp_rows:
        net[e.paid_by] += e.amount
        for s in db.scalars(select(models.ExpenseSplit).where(models.ExpenseSplit.expense_id == e.id)).all():
            net[s.user_id] -= s.amount
    settlements = db.scalars(select(models.Settlement).where(models.Settlement.group_id == group_id)).all()
    for s in settlements:
        net[s.payer_id] += s.amount
        net[s.receiver_id] -= s.amount
    return [{"user_id": uid, "name": db.get(models.User, uid).name, "net": round(value, 2)} for uid, value in net.items()]

@app.post("/api/groups/{group_id}/settlements")
def settle(group_id: int, data: schemas.SettlementIn, db: Session = Depends(get_db), user=Depends(current_user)):
    member_required(db, group_id, user.id)
    member_required(db, group_id, data.payer_id); member_required(db, group_id, data.receiver_id)
    if data.payer_id == data.receiver_id: raise HTTPException(400, "Payer and receiver must differ")
    db.add(models.Settlement(group_id=group_id, payer_id=data.payer_id, receiver_id=data.receiver_id, amount=data.amount))
    db.commit()
    return {"message": "Settlement recorded"}
