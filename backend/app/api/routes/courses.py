import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import case, func, select

from app.core.deps import AppServices, CurrentUser, DbSession, InstructorMembership, Membership
from app.db.models import ChatSession, Course, CourseMember, DocStatus, Document, MemberRole, User
from app.schemas.common import CourseIn, CourseOut, CourseUpdate, MemberIn, MemberOut
from app.services import storage

router = APIRouter(prefix="/courses", tags=["courses"])


async def _course_out(
    db: DbSession, course: Course, role: MemberRole, user_id: uuid.UUID
) -> CourseOut:
    doc_counts = await db.execute(
        select(
            func.count(Document.id),
            func.count(case((Document.status == DocStatus.INDEXED, 1))),
        ).where(Document.course_id == course.id)
    )
    total, indexed = doc_counts.one()
    sessions = await db.scalar(
        select(func.count(ChatSession.id)).where(
            ChatSession.course_id == course.id, ChatSession.user_id == user_id
        )
    )
    return CourseOut(
        id=course.id,
        name=course.name,
        description=course.description,
        created_at=course.created_at,
        role=role,
        document_count=total,
        indexed_count=indexed,
        session_count=sessions or 0,
    )


@router.get("", response_model=list[CourseOut])
async def list_courses(user: CurrentUser, db: DbSession) -> list[CourseOut]:
    rows = await db.execute(
        select(Course, CourseMember.role)
        .join(CourseMember, CourseMember.course_id == Course.id)
        .where(CourseMember.user_id == user.id)
        .order_by(Course.created_at.desc())
    )
    return [await _course_out(db, course, role, user.id) for course, role in rows.all()]


@router.post("", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
async def create_course(body: CourseIn, user: CurrentUser, db: DbSession) -> CourseOut:
    course = Course(name=body.name, description=body.description, created_by=user.id)
    db.add(course)
    await db.flush()
    db.add(CourseMember(course_id=course.id, user_id=user.id, role=MemberRole.INSTRUCTOR))
    await db.commit()
    await db.refresh(course)
    return await _course_out(db, course, MemberRole.INSTRUCTOR, user.id)


@router.get("/{course_id}", response_model=CourseOut)
async def get_course(course_id: uuid.UUID, member: Membership, db: DbSession) -> CourseOut:
    course = await db.get(Course, course_id)
    assert course is not None  # membership implies existence
    return await _course_out(db, course, member.role, member.user_id)


@router.patch("/{course_id}", response_model=CourseOut)
async def update_course(
    course_id: uuid.UUID, body: CourseUpdate, member: InstructorMembership, db: DbSession
) -> CourseOut:
    course = await db.get(Course, course_id)
    assert course is not None
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(course, field, value)
    await db.commit()
    await db.refresh(course)
    return await _course_out(db, course, member.role, member.user_id)


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: uuid.UUID, member: InstructorMembership, db: DbSession, services: AppServices
) -> None:
    course = await db.get(Course, course_id)
    assert course is not None
    await services.vectors.delete_course(course_id)
    await db.delete(course)
    await db.commit()
    storage.delete_course_files(services.settings, course_id)


@router.get("/{course_id}/members", response_model=list[MemberOut])
async def list_members(course_id: uuid.UUID, member: Membership, db: DbSession) -> list[MemberOut]:
    rows = await db.execute(
        select(CourseMember, User)
        .join(User, User.id == CourseMember.user_id)
        .where(CourseMember.course_id == course_id)
        .order_by(CourseMember.joined_at)
    )
    return [
        MemberOut(
            user_id=u.id, email=u.email, full_name=u.full_name, role=m.role, joined_at=m.joined_at
        )
        for m, u in rows.all()
    ]


@router.post("/{course_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
async def add_member(
    course_id: uuid.UUID, body: MemberIn, member: InstructorMembership, db: DbSession
) -> MemberOut:
    user = await db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No user with that email")
    existing = await db.get(CourseMember, (user.id, course_id))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already a member")
    new = CourseMember(course_id=course_id, user_id=user.id, role=body.role)
    db.add(new)
    await db.commit()
    await db.refresh(new)
    return MemberOut(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=new.role,
        joined_at=new.joined_at,
    )


@router.delete("/{course_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    course_id: uuid.UUID, user_id: uuid.UUID, member: InstructorMembership, db: DbSession
) -> None:
    if user_id == member.user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't remove yourself")
    target = await db.get(CourseMember, (user_id, course_id))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not a member")
    await db.delete(target)
    await db.commit()
