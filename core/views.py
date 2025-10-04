from django.shortcuts import render

# Create your views here.
# competition_app/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import *
from .forms import ContestantForm, ParticipationForm, TeamForm
from .utils import get_grade, POINTS_FOR_RANK, POINTS_FOR_GRADE
from django.db.models import Count, Sum
from django.contrib.auth import logout
# views.py
from django.contrib.auth import get_user_model

User = get_user_model()

def is_admin(user):
    return user.is_superuser or user.role == 'admin' # or use your custom check

def face_page(request):
    programs = Program.objects.all()
    teams = Team.objects.all()
    contestants = Contestant.objects.all()
    context = {
        'programs': programs,
        'teams': teams,
        'contestants' : contestants
    }
    return render(request, 'face.html', context)

@login_required
@user_passes_test(is_admin)
def lock_user(request, user_id):
    user = get_object_or_404(User, id=user_id)

    if user.role == 'team':   # only lock team role users
        user.is_active = False
        user.save()

    return redirect('view_users')

@login_required
@user_passes_test(is_admin)
def unlock_user(request, user_id):
    user = get_object_or_404(User, id=user_id)

    if user.role == 'team':   # only unlock team role users
        user.is_active = True
        user.save()

    return redirect('view_users')


# @login_required
# def dashboard_admin(request):
#     if request.user.role != 'admin': return redirect('dashboard_team')
#     programs = Program.objects.all()
#     teams = Team.objects.all()
#     return render(request, 'dashboard_admin.html', {'programs': programs, 'teams': teams})

@login_required
def dashboard_admin(request):
    programs = Program.objects.all()
    teams = Team.objects.all()
    pending_users = User.objects.filter(is_approved=False)
    context = {
        'programs': programs,
        'teams': teams,
        'pending_users': pending_users,
    }
    return render(request, 'dashboard_admin.html', context)


@login_required
def dashboard_team(request):
    if request.user.role != 'team': return redirect('dashboard_admin')
    team = request.user.team
    # In your view
    contestants = Contestant.objects.filter(team=team).order_by('category', 'name')
    return render(request, 'dashboard_team.html', {
        'contestants': contestants,
        'team': team
        })

@login_required
def add_contestant(request):
    if request.method == 'POST':
        form = ContestantForm(request.POST)
        if form.is_valid():
            contestant = form.save(commit=False)
            contestant.team = request.user.team
            contestant.save()
            return redirect('dashboard_team')
    else:
        form = ContestantForm()
    return render(request, 'add_contestant.html', {'form': form})

@login_required
def enter_marks_summary(request):
    if request.user.role != 'admin':
        return redirect('dashboard_team')

    # Get filter parameter
    program_id = request.GET.get('program')

    # Get all programs for the filter dropdown
    programs = Program.objects.all().order_by('name')

    # Filter participations based on program selection
    if program_id:
        participations = Participation.objects.filter(
            marks__isnull=False,
            program_id=program_id
        ).select_related('contestant__team', 'contestant__category', 'program').order_by('-marks')
        selected_program = Program.objects.get(id=program_id)
    else:
        participations = Participation.objects.filter(
            marks__isnull=False
        ).select_related('contestant__team', 'contestant__category', 'program').order_by('program__name', '-marks')
        selected_program = None

    # Calculate ranks and grades for all programs (or selected program)
    if program_id:
        program_participations = Participation.objects.filter(
            program_id=program_id,
            marks__isnull=False
        ).select_related('contestant__team', 'contestant__category', 'program').order_by('-marks')

        # Apply proper ranking with ties
        assign_ranks_with_ties(program_participations)

        for p in program_participations:
            p.grade = get_grade(p.marks)

            if not p.points_awarded:
                is_group = p.program.is_group
                category_name = p.contestant.category.name if p.contestant and p.contestant.category else None
                total_points = calculate_points(p.rank, p.grade, is_group, category_name)

                if total_points > 0:
                    tp, created = TeamPoints.objects.get_or_create(team=p.contestant.team)
                    tp.points += total_points
                    tp.save()
                    p.points_awarded = True

            p.save()
    else:
        for program in Program.objects.all():
            program_participations = Participation.objects.filter(
                program=program,
                marks__isnull=False
            ).select_related('contestant__team', 'contestant__category', 'program').order_by('-marks')

            # Apply proper ranking with ties
            assign_ranks_with_ties(program_participations)

            for p in program_participations:
                p.grade = get_grade(p.marks)

                if not p.points_awarded:
                    is_group = p.program.is_group
                    category_name = p.contestant.category.name if p.contestant and p.contestant.category else None
                    total_points = calculate_points(p.rank, p.grade, is_group, category_name)

                    if total_points > 0:
                        tp, created = TeamPoints.objects.get_or_create(team=p.contestant.team)
                        tp.points += total_points
                        tp.save()
                        p.points_awarded = True

                p.save()

    # Add calculated points to each participation for template display
    for p in participations:
        if p.points_awarded:
            is_group = p.program.is_group
            category_name = p.contestant.category.name if p.contestant and p.contestant.category else None
            total_points = calculate_points(p.rank, p.grade, is_group, category_name)

            if category_name and category_name.strip().upper() == "GENERAL":
                rank_points_map = {1: 10, 2: 6, 3: 3}
                grade_points_map = {'A': 10, 'B': 6, 'C': 3}
            else:
                rank_points_map = POINTS_FOR_RANK_GROUP if is_group else POINTS_FOR_RANK
                grade_points_map = POINTS_FOR_GRADE_GROUP if is_group else POINTS_FOR_GRADE

            # Always compute rank points
            p.rank_points = rank_points_map.get(p.rank, 0)
            p.grade_points = grade_points_map.get(p.grade, 0) if p.grade else 0
            p.total_points = p.rank_points + p.grade_points
        else:
            p.total_points = 0
            p.rank_points = 0
            p.grade_points = 0

    return render(request, 'enter_marks.html', {
        'participations': participations,
        'programs': programs,
        'selected_program': selected_program,
        'program_id': program_id,
    })


def assign_ranks_with_ties(participants):
    """
    Assign ranks to participants handling ties properly.
    For example: marks [90, 80, 80, 79] -> ranks [1, 2, 2, 3]
    """
    if not participants:
        return
    
    current_rank = 1
    previous_marks = None
    
    for participant in participants:
        if previous_marks is not None and participant.marks != previous_marks:
            # Different marks, increment rank by 1
            current_rank += 1
        
        participant.rank = current_rank
        previous_marks = participant.marks

@login_required
def team_marks_summary(request):
    # Only allow team users
    if request.user.role != 'team':
        return redirect('dashboard_admin')

    # Get the team of the logged-in user
    team = request.user.team

    # Get all participations of this team where marks are given
    participations = Participation.objects.filter(
        contestant__team=team,
        marks__isnull=False
    ).select_related('program', 'contestant').order_by('program__name', '-marks')

    # Calculate ranks and grades within each program
    for program in Program.objects.all():
        program_participations = Participation.objects.filter(
            program=program,
            marks__isnull=False
        ).order_by('-marks')

        for i, p in enumerate(program_participations, 1):
            if p.contestant.team == team:
                p.rank = i
                p.grade = get_grade(p.marks)
                if p.points_awarded and p.grade:
                    rank_points = POINTS_FOR_RANK.get(p.rank, 0)
                    grade_points = POINTS_FOR_GRADE.get(p.grade, 0)
                    p.total_points = rank_points + grade_points
                else:
                    p.total_points = 0

    # Add display points
    for p in participations:
        if p.points_awarded and p.grade:
            rank_points = POINTS_FOR_RANK.get(p.rank, 0)
            grade_points = POINTS_FOR_GRADE.get(p.grade, 0)
            p.total_points = rank_points + grade_points
            p.rank_points = rank_points
            p.grade_points = grade_points
        else:
            p.total_points = 0
            p.rank_points = 0
            p.grade_points = 0

    return render(request, 'team_marks_summary.html', {
        'team': team,
        'participations': participations,
    })


import xlwt
from django.http import HttpResponse

from django.db.models import F

@login_required
def results_view(request):
    # Fetch participations sorted by marks (highest first)
    participations = (
        Participation.objects.filter(marks__isnull=False)
        .select_related('program', 'contestant', 'contestant__team')
        .order_by('-marks')  # Sort by marks first
    )

    # Assign ranks with tie handling
    current_rank = 0
    last_marks = None
    for index, p in enumerate(participations, start=1):
        if p.marks != last_marks:
            current_rank = index
            last_marks = p.marks
        p.rank = current_rank

    return render(request, 'results.html', {'participations': participations})


@login_required
def export_excel(request):
    response = HttpResponse(content_type='application/ms-excel')
    response['Content-Disposition'] = 'attachment; filename="competition_results.xls"'

    wb = xlwt.Workbook(encoding='utf-8')
    ws = wb.add_sheet('Results')

    columns = ['Program', 'Contestant', 'Team', 'Marks', 'Grade', 'Rank']
    for col_num in range(len(columns)):
        ws.write(0, col_num, columns[col_num])

    rows = Participation.objects.filter(marks__isnull=False).values_list(
        'program__name', 'contestant__name', 'contestant__team__name',
        'marks', 'grade', 'rank'
    )
    for row_num, row in enumerate(rows, start=1):
        for col_num, value in enumerate(row):
            ws.write(row_num, col_num, value)

    wb.save(response)
    return response

@login_required
def leaderboard(request):
    teams = TeamPoints.objects.select_related('team').order_by('-points')
    return render(request, 'leaderboard.html', {'teams': teams})


from django.contrib.auth import authenticate, login
from django.contrib import messages


def landing_view(request):
    return render(request, 'landing.html')

from django.contrib.auth import authenticate, login
from django.shortcuts import redirect, render
from django.contrib import messages

def custom_login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if not user.is_superuser and not user.is_approved:
                messages.error(request, 'Account pending approval by admin.')
                return redirect('login')

            login(request, user)

            # role-based redirect
            if user.is_superuser or user.role == 'admin':
                return redirect('dashboard_admin')
            elif user.role == 'team':
                return redirect('dashboard_team')
            elif user.role == 'off_campus':
                return redirect('dashboard_off_campus')
            else:
                messages.error(request, 'Unknown role.')
                return redirect('login')
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'login.html')

from django.contrib.auth import get_user_model
User = get_user_model()

def signup_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        role = request.POST.get('role')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists. Choose another.")
            return render(request, 'signup.html')

        user = User.objects.create_user(
            username=username,
            password=password,
            role=role,
            is_active=True,  # still needed to be True for Django auth
            is_approved=False  # requires admin approval
        )
        messages.success(request, "Account created! Wait for admin approval.")
        return redirect('login')

    return render(request, 'signup.html')


def custom_logout_view(request):
    logout(request)
    return redirect('landing') 



@login_required
@user_passes_test(is_admin)
def pending_users(request):
    users = User.objects.filter(is_approved=False)
    return render(request, 'pending_users.html', {'users': users})

@login_required
@user_passes_test(is_admin)
def approve_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    user.is_approved = True
    user.save()
    return redirect('pending_users')

@login_required
@user_passes_test(is_admin)
def disapprove_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    user.is_approved = False
    user.save()
    return redirect('pending_users')

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.core.paginator import Paginator


User = get_user_model()

@user_passes_test(is_admin)
def view_users(request):
    query = request.GET.get('q')
    role = request.GET.get('role')

    users = User.objects.all()

    if query:
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query))
    if role:
        users = users.filter(role=role)

    paginator = Paginator(users, 10)  # 10 per page
    page = request.GET.get('page')
    users = paginator.get_page(page)

    return render(request, 'view_users.html', {
        'users': users,
        'search_term': query or '',
        'selected_role': role or '',
    })

@user_passes_test(is_admin)
def delete_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    user.delete()
    return redirect('view_users')


from django.contrib import messages

@user_passes_test(is_admin)
def edit_user(request, user_id):
    user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        user.username = request.POST.get('username')
        user.email = request.POST.get('email')
        user.role = request.POST.get('role')
        user.is_active = 'is_active' in request.POST
        user.save()
        messages.success(request, 'User updated successfully.')
        return redirect('view_users')

    return render(request, 'edit_user.html', {'user': user})


from .models import Program, Category


# add categroy by admin
from .models import Category

@login_required
def add_category(request):
    if not (request.user.is_superuser or request.user.role == 'admin'):
        return redirect('dashboard_team')  # or wherever non-admins should go

    if request.method == 'POST':
        name = request.POST.get('name').strip()
        if name:
            if Category.objects.filter(name__iexact=name).exists():
                messages.warning(request, f"Category '{name}' already exists.")
            else:
                Category.objects.create(name=name)
                messages.success(request, f"Category '{name}' added successfully.")
                return redirect('add_category')
        else:
            messages.error(request, "Category name cannot be empty.")

    categories = Category.objects.all().order_by('name')
    return render(request, 'add_category.html', {'categories': categories})


@login_required
def edit_category(request, category_id):
    if request.user.role != 'admin':
        return redirect('dashboard_team')
    
    category = get_object_or_404(Category, id=category_id)

    if request.method == 'POST':
        new_name = request.POST.get('name').strip()
        if new_name:
            category.name = new_name
            category.save()
            messages.success(request, "Category updated successfully.")
            return redirect('add_category')
        else:
            messages.error(request, "Name can't be empty.")

    return render(request, 'edit_category.html', {'category': category})


@login_required
def delete_category(request, category_id):
    if request.user.role != 'admin':
        return redirect('dashboard_team')
    
    category = get_object_or_404(Category, id=category_id)
    category.delete()
    messages.success(request, "Category deleted.")
    return redirect('add_category')

from .models import Program

import pandas as pd
from django.core.files.storage import FileSystemStorage

@login_required
def add_program(request):
    if not (request.user.is_superuser or request.user.role == 'admin'):
        return redirect('dashboard_team')

    categories = Category.objects.all()
    programs = Program.objects.all().order_by('-id')

    if request.method == 'POST':
        # Check if it's a bulk upload
        if 'excel_file' in request.FILES:
            excel_file = request.FILES['excel_file']

            try:
                # Read Excel file with pandas
                df = pd.read_excel(excel_file)

                # Expecting columns: "name" and "category"
                for _, row in df.iterrows():
                    name = row.get("name")
                    category_name = row.get("category")

                    if name and category_name:
                        try:
                            category = Category.objects.get(name=category_name)
                            Program.objects.create(name=name, category=category)
                        except Category.DoesNotExist:
                            messages.warning(request, f"Category '{category_name}' not found for program '{name}'. Skipped.")
                messages.success(request, "Bulk upload completed successfully.")
            except Exception as e:
                messages.error(request, f"Error processing Excel file: {e}")

            return redirect('add_program')

        else:
            # Single entry form
            name = request.POST.get('name')
            category_id = request.POST.get('category')

            if name and category_id:
                category = Category.objects.get(id=category_id)
                Program.objects.create(name=name, category=category)
                messages.success(request, f"Program '{name}' added successfully under {category.name}.")
                return redirect('add_program')
            else:
                messages.error(request, "All fields are required.")

    return render(request, 'add_program.html', {'categories': categories, 'programs': programs})

from django.http import JsonResponse

@login_required
def toggle_is_group(request, program_id):
    if not (request.user.is_superuser or request.user.role == 'admin'):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    program = get_object_or_404(Program, id=program_id)
    program.is_group = not program.is_group
    program.save()

    return JsonResponse({
        'success': True,
        'program_id': program.id,
        'is_group': program.is_group,
        'status': 'Group' if program.is_group else 'Individual'
    })



@login_required
def edit_program(request, program_id):
    if request.user.role != 'admin':
        return redirect('dashboard_team')

    program = get_object_or_404(Program, id=program_id)
    categories = Category.objects.all()

    if request.method == 'POST':
        name = request.POST.get('name').strip()
        category_id = request.POST.get('category')

        if name and category_id:
            category = get_object_or_404(Category, id=category_id)
            program.name = name
            program.category = category
            program.save()
            messages.success(request, "Program updated successfully.")
            return redirect('add_program')
        else:
            messages.error(request, "All fields are required.")

    return render(request, 'edit_program.html', {
        'program': program,
        'categories': categories
    })

@login_required
def delete_program(request, program_id):
    if request.user.role != 'admin':
        return redirect('dashboard_team')

    program = get_object_or_404(Program, id=program_id)
    program.delete()
    messages.success(request, "Program deleted successfully.")
    return redirect('add_program')

@login_required
def bulk_delete_programs(request):
    if request.user.role != 'admin':
        return redirect('dashboard_team')

    if request.method == "POST":
        program_ids = request.POST.getlist("program_ids")  # get selected IDs
        if program_ids:
            Program.objects.filter(id__in=program_ids).delete()
            messages.success(request, f"{len(program_ids)} programs deleted successfully.")
        else:
            messages.warning(request, "No programs selected.")
        return redirect('add_program')

    # If GET request → show programs list with checkboxes
    programs = Program.objects.all().order_by('name')
    return render(request, "bulk_delete_programs.html", {"programs": programs})

def program_list(request):
    programs = Program.objects.all().order_by('category__name', 'name')
    categories = Category.objects.all()

    context = {
        'programs':programs,
        'categories': categories
    }
    return render(request, 'program_list.html', context)


@login_required
def add_group_program(request):
    if not (request.user.is_superuser or request.user.role == 'admin'):
        return redirect('dashboard_team')

    categories = Category.objects.all()
    programs = Program.objects.filter(is_group=True).order_by('-id')

    if request.method == 'POST':
        name = request.POST.get('name')
        category_id = request.POST.get('category')

        if name and category_id:
            category = get_object_or_404(Category, id=category_id)
            Program.objects.create(name=name, category=category, is_group=True)
            messages.success(request, f"Group Program '{name}' added successfully.")
            return redirect('add_group_program')
        else:
            messages.error(request, "All fields are required.")

    return render(request, 'add_group_program.html', {'categories': categories, 'programs': programs})


@login_required
def assign_group_program(request):
    if not (request.user.is_superuser or request.user.role == 'admin'):
        return redirect('dashboard_team')

    categories = Category.objects.all()

    if request.method == 'POST':
        program_id = request.POST.get('program')
        participant_ids = request.POST.getlist('participants')

        if len(participant_ids) > 5:
            messages.error(request, "You can select a maximum of 5 participants.")
            return redirect('assign_group_program')

        program = get_object_or_404(Program, id=program_id)
        group_participation = GroupParticipation.objects.create(program=program)
        group_participation.contestants.set(participant_ids) 

        messages.success(request, "Participants assigned successfully.")
        return redirect('assign_group_program')

    return render(request, 'assign_group_program.html', {'categories': categories})


from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

@login_required
@csrf_exempt
def get_group_programs(request):
    category_id = request.POST.get('category_id')
    programs = Program.objects.filter(category_id=category_id, is_group=True)
    program_list = [{"id": p.id, "name": p.name} for p in programs]
    return JsonResponse({"programs": program_list})

@login_required
@csrf_exempt
def get_participants_by_category(request):
    category_id = request.POST.get('category_id')
    contestants = Contestant.objects.filter(category_id=category_id)
    contestant_list = [{"id": c.id, "name": c.name} for c in contestants]
    return JsonResponse({"contestants": contestant_list})


@login_required
def participant_list(request):
    user = request.user
    team_id = request.GET.get('team_id')
    category_id = request.GET.get('category_id')

    teams = Team.objects.all()
    categories = Category.objects.all()
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')

    # 👇 If the logged-in user is a team user, filter to only their team participants
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
        team_id = user.team.id  # Fix context
    else:
        # For admin users, allow filtering
        if team_id:
            participants = participants.filter(team_id=team_id)
        if category_id:
            participants = participants.filter(category_id=category_id)

    return render(request, 'participants_list.html', {
        'teams': teams,
        'categories': categories,
        'participants': participants,
        'selected_team_id': int(team_id) if team_id else None,
        'selected_category_id': int(category_id) if category_id else None
    })

@login_required
def participants_by_category(request):
    user = request.user
    
    # Get all categories and participants
    categories = Category.objects.all().order_by('name')
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')
    
    # If the logged-in user is a team user, filter to only their team participants
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
    
    # Group participants by category
    participants_by_category = {}
    for category in categories:
        category_participants = participants.filter(category=category)
        if category_participants.exists():
            participants_by_category[category] = category_participants
    
    return render(request, 'participants_by_category.html', {
        'participants_by_category': participants_by_category,
        'total_participants': participants.count(),
    })


@login_required
def participants_by_team(request):
    user = request.user
    
    # Get all teams and participants
    teams = Team.objects.all().order_by('name')
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')
    
    # If the logged-in user is a team user, show only their team
    if hasattr(user, 'team'):
        teams = Team.objects.filter(id=user.team.id)
        participants = participants.filter(team=user.team)
    
    # Group participants by team
    participants_by_team = {}
    for team in teams:
        team_participants = participants.filter(team=team)
        if team_participants.exists():
            participants_by_team[team] = team_participants
    
    return render(request, 'participants_by_team.html', {
        'participants_by_team': participants_by_team,
        'total_participants': participants.count(),
    })


import pandas as pd
from django.contrib import messages
from .forms import ContestantForm
from .models import Contestant, Team, Category

def add_participant(request):
    if request.method == 'POST':
        # --- Bulk Upload Excel ---
        if 'excel_file' in request.FILES:
            excel_file = request.FILES['excel_file']
            try:
                df = pd.read_excel(excel_file)

                # Expect columns: name, team, category
                for _, row in df.iterrows():
                    name = row.get("name")
                    team_name = row.get("team")
                    category_name = row.get("category")

                    if not (name and team_name and category_name):
                        continue  # skip incomplete rows

                    try:
                        team = Team.objects.get(name=team_name)
                        category = Category.objects.get(name=category_name)

                        Contestant.objects.create(
                            name=name,
                            team=team,
                            category=category,
                            # chest_no auto-assigned in save()
                            # total_points default=0
                        )
                    except Team.DoesNotExist:
                        messages.warning(request, f"Team '{team_name}' not found. Skipped {name}.")
                    except Category.DoesNotExist:
                        messages.warning(request, f"Category '{category_name}' not found. Skipped {name}.")

                messages.success(request, "Bulk participant upload successful.")
            except Exception as e:
                messages.error(request, f"Error processing Excel: {e}")

            return redirect('participant_list')

        # --- Single Form Entry ---
        else:
            form = ContestantForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "Participant added successfully.")
                return redirect('participant_list')
    else:
        form = ContestantForm()

    return render(request, 'participant_form.html', {'form': form})


def edit_participant(request, id):
    participant = get_object_or_404(Contestant, id=id)
    if request.method == 'POST':
        form = ContestantForm(request.POST, instance=participant)
        if form.is_valid():
            form.save()
            return redirect('participant_list')
    else:
        form = ContestantForm(instance=participant)
    return render(request, 'participant_form.html', {'form': form})

def delete_participant(request, id):
    participant = get_object_or_404(Contestant, id=id)
    participant.delete()
    return redirect('participant_list')

def participants_list(request):
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')
    return render(request, 'participants_list.html', {'participants': participants})


def add_team(request):
    form = TeamForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('add_team')
    teams = Team.objects.all()
    return render(request, 'add_team_modal.html', {'form': form, 'teams': teams})

def edit_team(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    form = TeamForm(request.POST or None, instance=team)
    if form.is_valid():
        form.save()
        return redirect('add_team')
    return render(request, 'edit_team.html', {'form': form, 'team': team})

def delete_team(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    team.delete()
    return redirect('add_team')


# views.py
from .forms import ParticipationForm

# views.py
from django.http import JsonResponse
from .models import Program, Participation, Contestant, Category

def get_programs_for_contestant(request):
    contestant_id = request.GET.get('contestant_id')
    category_id = request.GET.get('category_id')

    if not contestant_id or not category_id:
        return JsonResponse({'programs': []})

    # programs already assigned to contestant
    assigned_programs = Participation.objects.filter(
        contestant_id=contestant_id
    ).values_list('program_id', flat=True)

    try:
        contestant = Contestant.objects.get(id=contestant_id)
        selected_category = Category.objects.get(id=category_id)
    except (Contestant.DoesNotExist, Category.DoesNotExist):
        return JsonResponse({'programs': []})

    # Logic: contestant category + general
    if contestant.category.name.lower() == "junior":
        categories_to_include = ["Junior", "General"]
    elif contestant.category.name.lower() == "senior":
        categories_to_include = ["Senior", "General"]
    else:  # if contestant is General (rare case)
        categories_to_include = ["General"]

    programs = Program.objects.filter(
        category__name__in=categories_to_include
    ).exclude(id__in=assigned_programs)

    return JsonResponse({
        'programs': list(programs.values('id', 'name'))
    })




from django.http import JsonResponse
from .models import Contestant, Category

def get_contestants(request):
    team_id = request.GET.get('team_id')
    category_id = request.GET.get('category_id')

    contestants = Contestant.objects.none()

    if team_id and category_id:
        try:
            category = Category.objects.get(id=category_id)

            if category.name.lower() == "general":
                # Fetch contestants from Junior + Senior
                contestants = Contestant.objects.filter(
                    team_id=team_id,
                    category__name__in=["JUNIOR", "SENIOR"]
                )
            else:
                # Fetch contestants only in that category
                contestants = Contestant.objects.filter(
                    team_id=team_id,
                    category=category
                )
        except Category.DoesNotExist:
            pass

    return JsonResponse({
        'contestants': list(contestants.values('id', 'name'))
    })



@login_required
def assign_programs(request):
    teams = Team.objects.all()
    categories = Category.objects.all()

    contestants = Contestant.objects.none()
    programs = Program.objects.none()

    team_id = request.GET.get('team')
    category_id = request.GET.get('category')

    if team_id and category_id:
        try:
            selected_category = Category.objects.get(id=category_id)

            if selected_category.name.lower() == "general":
                # contestants from Junior + Senior
                contestants = Contestant.objects.filter(
                    team_id=team_id,
                    category__name__in=["JUNIOR", "SENIOR", "SUBJUNIOR"]
                )
                # programs only from General
                programs = Program.objects.filter(category=selected_category)
            else:
                contestants = Contestant.objects.filter(
                    team_id=team_id,
                    category=selected_category
                )
                programs = Program.objects.filter(category=selected_category)

        except Category.DoesNotExist:
            pass

    if request.method == 'POST':
        contestant_id = request.POST.get('contestant')
        selected_programs = request.POST.getlist('programs')

        if len(selected_programs) > 5:
            messages.error(request, "You can only select up to 5 programs.")
        else:
            for prog_id in selected_programs:
                Participation.objects.get_or_create(
                    contestant_id=contestant_id,
                    program_id=prog_id
                )
            messages.success(request, "Programs assigned successfully!")
            return redirect('assign_programs')

    return render(request, 'assign_programs.html', {
        'teams': teams,
        'categories': categories,
        'contestants': contestants,
        'programs': programs,
    })


@login_required
def edit_assigned_programs(request, contestant_id):
    contestant = get_object_or_404(Contestant, id=contestant_id)

    # ✅ Get programs in contestant's category OR "General"
    all_programs = Program.objects.filter(
        Q(category=contestant.category) | Q(category__name="GENERAL")
    )

    # Already assigned
    assigned_programs = Participation.objects.filter(contestant=contestant).values_list('program_id', flat=True)

    if request.method == "POST":
        selected_program_ids = request.POST.getlist('programs')

        # Clear old assignments
        Participation.objects.filter(contestant=contestant).delete()

        # Save new assignments
        for program_id in selected_program_ids:
            Participation.objects.create(contestant=contestant, program_id=program_id)

        messages.success(request, "Programs updated successfully.")
        return redirect("assigned_programs")  # adjust to your URL name

    return render(request, "edit_assigned_programs.html", {
        "contestant": contestant,
        "all_programs": all_programs,   # ✅ category + GENERAL
        "assigned_program_ids": list(assigned_programs),
    })

from django.shortcuts import render
from .models import Participation
from django.shortcuts import render
from .models import Participation, Team, Category

@login_required
def view_assigned_programs(request):
    team_id = request.GET.get('team')
    category_id = request.GET.get('category')

    participations = Participation.objects.select_related(
        'contestant__team', 'contestant__category', 'program__category'
    )

    # Force filter by team if user is a team user
    if hasattr(request.user, 'team'):
        team_id = request.user.team.id
        participations = participations.filter(contestant__team_id=team_id)
    elif team_id:
        participations = participations.filter(contestant__team_id=team_id)

    if category_id:
        participations = participations.filter(
            Q(contestant__category_id=category_id) | Q(program__category_id=category_id)
        )

    context = {
        'participations': participations.order_by('contestant__team__name'),
        'teams': Team.objects.all(),
        'categories': Category.objects.all(),
        'selected_team': int(team_id) if team_id else '',
        'selected_category': int(category_id) if category_id else '',
    }
    return render(request, 'assigned_programs.html', context)

from django.utils import timezone


@login_required
def download_participation_list_pdf(request):
    """Download Participation List PDF"""
    user = request.user

    # Fetch contestants sorted by team, then category, then chest_no
    participants = Contestant.objects.select_related(
        'team', 'category', 'participation__program'
    ).order_by('team__name', 'category__name', 'chest_no')

    # If team user → filter
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)

    # File name
    filename = "participation_list.pdf"
    if hasattr(user, 'team'):
        filename = f"{user.team.name}_participation_list.pdf"

    # Context
    context = {
        'fest_name': "Annual Arts Fest 2025",   # 👈 set your fest name dynamically if stored
        'date': timezone.now().strftime("%d-%m-%Y"),
        'participants': participants,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }

    # Generate PDF
    template_path = 'participation_list_pdf.html'
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    template = get_template(template_path)
    html = template.render(context)
    pisa_status = pisa.CreatePDF(html, dest=response)

    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response

@login_required
def delete_assigned_program(request, participation_id):
    participation = get_object_or_404(Participation, id=participation_id)
    participation.delete()
    messages.success(request, "Program assignment removed successfully.")
    return redirect('assigned_programs')  # redirect to the list view




from django.shortcuts import render
from core.models import Participation, Program

def view_results(request):
    # fetch programs with results
    programs = Program.objects.filter(participation__marks__isnull=False).distinct()

    program_results = []
    for program in programs:
        results = (
            Participation.objects
            .filter(program=program, marks__isnull=False)
            .order_by('rank')
        )

        # Add calculated points for display
        for p in results:
            if p.points_awarded:
                rank_points = POINTS_FOR_RANK.get(p.rank, 0)
                grade_points = POINTS_FOR_GRADE.get(p.grade, 0) if p.grade else 0
                p.total_points = rank_points + grade_points
                p.rank_points = rank_points
                p.grade_points = grade_points
            else:
                p.total_points = 0
                p.rank_points = 0
                p.grade_points = 0

        program_results.append({
            'program': program,
            'results': results,
            'program_total_points': sum(p.total_points for p in results)
        })

    # ✅ Fix: fetch categories correctly through program__participation
    categories = Category.objects.filter(
        program__participation__marks__isnull=False
    ).distinct()

    return render(
        request,
        'view_results.html',
        {'program_results': program_results, "categories": categories}
    )

from django.template.loader import get_template
from django.http import HttpResponse
from xhtml2pdf import pisa

def render_to_pdf(template_src, context_dict={}):
    template = get_template(template_src)
    html = template.render(context_dict)
    response = HttpResponse(content_type='application/pdf')
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response

def results_pdf(request):
    programs = Program.objects.filter(participation__marks__isnull=False).distinct()

    program_results = []
    for program in programs:
        results = (
            Participation.objects
            .filter(program=program, marks__isnull=False)
            .order_by('rank')
        )
        program_results.append({
            'program': program,
            'results': results
        })

    context = {'program_results': program_results}
    return render_to_pdf('results_pdf.html', context)



from django.forms import modelformset_factory
from django.db import transaction
from django.http import JsonResponse
from .models import Category, Program, Participation, TeamPoints
from .forms import MarkEntryForm

# Constants for point calculation
POINTS_FOR_RANK = {1: 6, 2: 3, 3: 1}
POINTS_FOR_GRADE = {'A': 6, 'B': 3, 'C': 1}
POINTS_FOR_RANK_GROUP = {1: 15, 2: 10, 3: 5}
POINTS_FOR_GRADE_GROUP = {'A': 15, 'B': 10, 'C': 5}
GROUP_POINTS_BY_COUNT = {
    2: {'rank': 5, 'grade': 8},
    3: {'rank': 7, 'grade': 10},
    4: {'rank': 9, 'grade': 12},
    5: {'rank': 10, 'grade': 15},
}

def get_grade(marks):
    """Convert marks to grade"""
    if marks is None:
        return None
    if marks >= 80:
        return 'A'
    elif marks >= 60:
        return 'B'
    elif marks >= 50:
        return 'C'
    return None

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.forms import modelformset_factory
from .models import Category, Program, Participation
from .forms import MarkEntryForm
from django.contrib.auth.decorators import login_required

@login_required
def add_marks(request):
    if request.user.role != 'admin':
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('dashboard_team')

    category_id = request.GET.get('category')
    program_id = request.GET.get('program')

    categories = Category.objects.all().order_by('name')
    programs = Program.objects.none()

    if category_id:
        try:
            category_id = int(category_id)
            programs = Program.objects.filter(category_id=category_id).order_by('name')
        except (ValueError, TypeError):
            category_id = None

    participations = Participation.objects.none()
    program = None

    if program_id:
        try:
            program_id = int(program_id)
            program = Program.objects.get(id=program_id)

            base_qs = Participation.objects.filter(
                program_id=program_id
            ).select_related(
                'contestant',
                'contestant__team',
                'contestant__category',
                'program'
            )

            if program.is_group:
                # 👉 For group programs, pick only 1 participation per team
                team_ids = base_qs.values_list('contestant__team', flat=True).distinct()
                participations = base_qs.filter(contestant__team__in=team_ids) \
                                        .order_by('contestant__team__name')
            else:
                # Normal case: all contestants
                participations = base_qs.order_by('contestant__chest_no')

        except (ValueError, TypeError, Program.DoesNotExist):
            program_id = None

    ParticipationFormSet = modelformset_factory(
        Participation,
        form=MarkEntryForm,
        extra=0,
        can_delete=False
    )

    if request.method == 'POST':
        formset = ParticipationFormSet(request.POST, queryset=participations)
        if formset.is_valid():
            with transaction.atomic():
                instances = formset.save(commit=False)
                saved_count = 0
                for instance in instances:
                    if instance.marks is not None:
                        # 👉 If group program, update all team members
                        if program and program.is_group:
                            Participation.objects.filter(
                                program=program,
                                contestant__team=instance.contestant.team
                            ).update(marks=instance.marks)
                        else:
                            instance.save()
                        saved_count += 1

                if saved_count > 0 and category_id and program_id:
                    calculate_rankings_and_points(category_id, program_id)

                messages.success(request, f'Successfully saved marks for {saved_count} participants!')

            return redirect(f"{request.path}?category={category_id}&program={program_id}")
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        formset = ParticipationFormSet(queryset=participations)

    context = {
        'categories': categories,
        'programs': programs,
        'formset': formset,
        'selected_category': str(category_id) if category_id else '',
        'selected_program': str(program_id) if program_id else '',
        'participations': participations,
        'program': program,
    }
    return render(request, 'add_marks.html', context)



@login_required
def undo_points(request, participation_id):
    if request.user.role != 'admin':
        messages.error(request, 'You do not have permission to perform this action.')
        return redirect('dashboard_team')

    try:
        participation = Participation.objects.select_related(
            'contestant__team', 'program'
        ).get(id=participation_id)

        if not participation.points_awarded:
            messages.warning(request, "Points were not awarded for this participant.")
            return redirect('add_marks')  # you can also redirect back with query params

        # calculate total points that were awarded
        from .utils import POINTS_FOR_RANK, POINTS_FOR_GRADE, get_grade  # adjust import if needed

        rank_points = POINTS_FOR_RANK.get(participation.rank, 0)
        grade_points = POINTS_FOR_GRADE.get(participation.grade, 0)
        total_points = rank_points + grade_points

        # deduct from team
        team = participation.contestant.team
        team_points, _ = TeamPoints.objects.get_or_create(team=team)
        team_points.points = max(0, team_points.points - total_points)
        team_points.save()

        # reset participant fields
        participation.rank = None
        participation.grade = None
        participation.points_awarded = False
        participation.save()

        messages.success(request, f"✅ Points for {participation.contestant.name} in {participation.program.name} have been undone.")

    except Participation.DoesNotExist:
        messages.error(request, "Participation not found.")

    return redirect(request.META.get('HTTP_REFERER', 'add_marks'))





def award_points_to_team(participant, total_points):
    """Award points to team and mark participant as points awarded"""
    team = participant.contestant.team
    team_points, created = TeamPoints.objects.get_or_create(team=team, defaults={'points': 0})
    team_points.points += total_points
    team_points.save()
    team.total_points += total_points
    team.save()
    participant.points_awarded = True


from django.db.models import Avg

def calculate_rankings_and_points(category_id, program_id):
    """
    Calculate rankings and award points for a specific program in a category.
    Handles both individual and group programs with proper tie handling.
    """
    try:
        # Get program instance to check if group or individual
        program = Program.objects.get(id=program_id)
        is_group_program = program.is_group
        
        participants = Participation.objects.filter(
            contestant__category_id=category_id,
            program_id=program_id,
            marks__isnull=False
        ).select_related('contestant', 'contestant__team').order_by('-marks', 'contestant__chest_no')
        
        # Reset all rankings first
        Participation.objects.filter(
            contestant__category_id=category_id,
            program_id=program_id
        ).update(rank=None, grade=None)
        
        # Apply proper ranking with ties
        assign_ranks_with_ties(participants)
        
        for participant in participants:
            participant.grade = get_grade(participant.marks)
            
            if not participant.points_awarded:
                category_name = participant.contestant.category.name if participant.contestant.category else None
                total_points = calculate_points(participant.rank, participant.grade, is_group_program, category_name)
                
                if total_points > 0:
                    award_points_to_team(participant, total_points)
            
            participant.save()
            
    except Exception as e:
        print(f"Error in calculate_rankings_and_points: {e}")
        raise



def calculate_points(rank, grade, is_group=False, category_name=None):
    """
    Calculate points based on whether program is group or individual,
    and handle special case for 'General' category.
    """
    if category_name and category_name.strip().upper() == "GENERAL":
        # General category point mapping
        rank_points_map = {1: 10, 2: 6, 3: 3}
        grade_points_map = {'A': 10, 'B': 6, 'C': 3}
    else:
        # Default point mapping
        rank_points_map = POINTS_FOR_RANK_GROUP if is_group else POINTS_FOR_RANK
        grade_points_map = POINTS_FOR_GRADE_GROUP if is_group else POINTS_FOR_GRADE
    
    rank_points = rank_points_map.get(rank, 0)
    grade_points = grade_points_map.get(grade, 0) if grade else 0
    return rank_points + grade_points



@login_required
def get_programs_by_category(request):
    """
    AJAX view to get programs filtered by category
    """
    category_id = request.GET.get('category_id')
    programs = []

    if category_id:
        try:
            programs_qs = Program.objects.filter(
                category_id=int(category_id)
            ).order_by('name')
            programs = [{'id': p.id, 'name': p.name} for p in programs_qs]
        except (ValueError, TypeError):
            pass

    return JsonResponse({'programs': programs})


from django.db.models import Count, Q, Sum
from .models import Team, TeamPoints, Participation



@login_required
def team_leaderboard(request):
    """Display team leaderboard with points breakdown"""

    teams = Team.objects.all().order_by('name')
    team_stats = []

    for team in teams:
        participations = Participation.objects.filter(contestant__team=team)

        total_participations = participations.count()
        marked_participations = participations.filter(marks__isnull=False).count()
        awarded_participations = participations.filter(points_awarded=True).count()

        # initialize breakdown
        rank_points = 0
        grade_points = 0
        winners = 0
        grade_a = grade_b = grade_c = 0
        first_place = second_place = third_place = 0

        # loop through awarded participations and calculate points with SAME logic
        total_calculated_points = 0
        for p in participations.filter(points_awarded=True):
            is_group = p.program.is_group
            category_name = p.program.category.name if p.program and p.program.category else None

            # use same function as enter_marks_summary
            points = calculate_points(p.rank, p.grade, is_group, category_name)
            total_calculated_points += points

            # breakdowns (for display)
            if p.rank in [1, 2, 3]:
                winners += 1
                if p.rank == 1: first_place += 1
                if p.rank == 2: second_place += 1
                if p.rank == 3: third_place += 1

            if p.grade == 'A': grade_a += 1
            if p.grade == 'B': grade_b += 1
            if p.grade == 'C': grade_c += 1

        # Update TeamPoints table
        team_points_obj, created = TeamPoints.objects.get_or_create(team=team)
        if team_points_obj.points != total_calculated_points:
            team_points_obj.points = total_calculated_points
            team_points_obj.save()

        team_stats.append({
            'team': team,
            'total_points': total_calculated_points,
            'rank_points': rank_points,
            'grade_points': grade_points,
            'total_participations': total_participations,
            'marked_participations': marked_participations,
            'awarded_participations': awarded_participations,
            'winners': winners,
            'first_place': first_place,
            'second_place': second_place,
            'third_place': third_place,
            'grade_a': grade_a,
            'grade_b': grade_b,
            'grade_c': grade_c,
        })

    # sort, rank, and overall stats
    team_stats.sort(key=lambda x: x['total_points'], reverse=True)
    for i, team_stat in enumerate(team_stats, 1):
        team_stat['position'] = i

    top_teams = team_stats[:3] if len(team_stats) >= 3 else team_stats

    context = {
        'team_stats': team_stats,
        'top_teams': top_teams,
        'total_teams': len(team_stats),
        'total_points_distributed': sum(ts['total_points'] for ts in team_stats),
        'total_participations_all': sum(ts['total_participations'] for ts in team_stats),
        'total_winners_all': sum(ts['winners'] for ts in team_stats),
    }
    return render(request, 'team_leaderboard.html', context)

from collections import defaultdict

def team_detail(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    participations = Participation.objects.filter(
        contestant__team=team
    ).select_related("program", "contestant")

    total_points = 0
    winners = []
    others = []
    programs_performance = defaultdict(list)

    for p in participations:
        category_name = p.program.category.name if p.program and p.program.category else None
        points = calculate_points(p.rank, p.grade, p.program.is_group, category_name) if p.points_awarded else 0

        total_points += points
        record = {
            "p": p,
            "points": points,
            "status": "✅ Awarded" if p.points_awarded else "⏳ Pending"
        }

        if p.rank and p.rank <= 3:
            winners.append(record)
        else:
            others.append(record)

        programs_performance[p.program.name].append(record)

    context = {
        "team": team,
        "team_points": total_points,
        "total_winners": len(winners),
        "total_participations": participations.count(),
        "programs_performance": programs_performance,
        "winners": winners,
        "others": others,
    }
    return render(request, "team_detail.html", context)


from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
from .models import Contestant

@login_required
def download_participants_pdf(request):
    user = request.user
    
    # Get participants based on user role
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')
    
    # If the logged-in user is a team user, filter to only their team participants
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
        filename = f"{user.team.name}_participants.pdf"
    else:
        # Admin users can download all participants
        filename = "all_participants.pdf"
    
    template_path = 'pdf_template.html'
    context = {
        'participants': participants,
        'user': user,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    template = get_template(template_path)
    html = template.render(context)
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response


# Optional: Create separate PDF download functions for specific views
@login_required
def download_category_participants_pdf(request):
    user = request.user
    category_id = request.GET.get('category_id')
    
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')
    
    # Filter by team if team user
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
    
    # Filter by category if specified
    if category_id:
        participants = participants.filter(category_id=category_id)
        try:
            category = Category.objects.get(id=category_id)
            filename = f"{category.name}_participants.pdf"
        except Category.DoesNotExist:
            filename = "category_participants.pdf"
    else:
        filename = "participants_by_category.pdf"
    
    template_path = 'pdf_template.html'
    context = {
        'participants': participants,
        'user': user,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None,
        'category_filter': category.name if category_id else None
    }
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    template = get_template(template_path)
    html = template.render(context)
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response


@login_required
def download_team_participants_pdf(request):
    user = request.user
    team_id = request.GET.get('team_id')
    
    participants = Contestant.objects.select_related('team', 'category').order_by('chest_no')
    
    # If team user, they can only download their own team
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
        filename = f"{user.team.name}_participants.pdf"
    else:
        # Admin can download specific team or all teams
        if team_id:
            participants = participants.filter(team_id=team_id)
            try:
                team = Team.objects.get(id=team_id)
                filename = f"{team.name}_participants.pdf"
            except Team.DoesNotExist:
                filename = "team_participants.pdf"
        else:
            filename = "participants_by_team.pdf"
    
    template_path = 'pdf_template.html'
    context = {
        'participants': participants,
        'user': user,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None,
        'team_filter': team.name if team_id else None
    }
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    template = get_template(template_path)
    html = template.render(context)
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response


@login_required
def program_participants(request):
    """Show participants for a specific program"""
    user = request.user
    program_id = request.GET.get('program_id')
    
    # Get all programs for the dropdown
    programs = Program.objects.all().order_by('name')
    participants = None
    selected_program = None
    
    if program_id:
        try:
            selected_program = Program.objects.get(id=program_id)
            participants = Contestant.objects.filter(
                program=selected_program
            ).select_related('team', 'category').order_by('chest_no')
            
            # If team user, filter to only their team participants
            if hasattr(user, 'team'):
                participants = participants.filter(team=user.team)
                
        except Program.DoesNotExist:
            selected_program = None
            participants = None
    
    return render(request, 'program_participants.html', {
        'programs': programs,
        'participants': participants,
        'selected_program': selected_program,
        'selected_program_id': int(program_id) if program_id else None,
    })


@login_required
def download_green_room_pdf(request, program_id):
    """Download Green Room Sign Sheet PDF"""
    try:
        program = Program.objects.get(id=program_id)
    except Program.DoesNotExist:
        return HttpResponse('Program not found', status=404)

    user = request.user
    participants = Contestant.objects.filter(
        participation__program=program
    ).select_related('team', 'category').order_by('chest_no')

    # Filter by team if team user
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
        filename = f"{program.name}_{user.team.name}_green_room.pdf"
    else:
        filename = f"{program.name}_green_room.pdf"

    template_path = 'green_room_pdf.html'
    context = {
        'program': program,
        'participants': participants,
        'user': user,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response


@login_required
def green_room_list(request, program_id):
    """Show Green Room Sign Sheet as normal Django page (HTML table)"""
    try:
        program = Program.objects.get(id=program_id)
    except Program.DoesNotExist:
        return HttpResponse('Program not found', status=404)

    user = request.user
    participants = Contestant.objects.filter(
        participation__program=program
    ).select_related('team', 'category').order_by('chest_no')

    # Filter if team user
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)

    context = {
        'program': program,
        'participants': participants,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }
    return render(request, 'green_room_list.html', context)



@login_required
def download_call_list_pdf(request, program_id):
    """Download Call List PDF"""
    try:
        program = Program.objects.get(id=program_id)
    except Program.DoesNotExist:
        return HttpResponse('Program not found', status=404)
    
    user = request.user
    participants = Contestant.objects.filter(
         participation__program=program
    ).select_related('team', 'category').order_by('chest_no')
    
    # Filter by team if team user
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
        filename = f"{program.name}_{user.team.name}_call_list.pdf"
    else:
        filename = f"{program.name}_call_list.pdf"
    
    template_path = 'call_list_pdf.html'
    context = {
        'program': program,
        'participants': participants,
        'user': user,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    template = get_template(template_path)
    html = template.render(context)
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response


@login_required
def download_valuation_form_pdf(request, program_id):
    """Download Valuation Form PDF"""
    try:
        program = Program.objects.get(id=program_id)
    except Program.DoesNotExist:
        return HttpResponse('Program not found', status=404)
    
    user = request.user
    participants = Contestant.objects.filter(
         participation__program=program
    ).select_related('team', 'category').order_by('chest_no')
    
    # Filter by team if team user
    if hasattr(user, 'team'):
        participants = participants.filter(team=user.team)
        filename = f"{program.name}_{user.team.name}_valuation.pdf"
    else:
        filename = f"{program.name}_valuation.pdf"
    
    template_path = 'valuation_form.html'
    context = {
        'program': program,
        'participants': participants,
        'user': user,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    template = get_template(template_path)
    html = template.render(context)
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response


def list_page(request):
    return render(request, 'list_page.html')

@login_required
def download_all_call_lists_pdf(request):
    """Download Call List PDF for all programs"""
    user = request.user
    
    # Fetch all programs
    programs = Program.objects.all().order_by('name')

    # Collect participants for each program
    program_participants = []
    for program in programs:
        participants = Contestant.objects.filter(
            participation__program=program
        ).select_related('team', 'category').order_by('chest_no')

        # Filter by team if user is team-based
        if hasattr(user, 'team'):
            participants = participants.filter(team=user.team)

        program_participants.append({
            'program': program,
            'participants': participants
        })

    # Prepare filename
    if hasattr(user, 'team'):
        filename = f"all_programs_{user.team.name}_call_list.pdf"
    else:
        filename = "all_programs_call_list.pdf"

    # Render template
    template_path = 'all_call_list_pdf.html'  # New template for all programs
    context = {
        'program_participants': program_participants,
        'user': user,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response


def chest_number(request):
    contestant = Contestant.objects.all()

    context = {
        'contestant' : contestant
    }
    return render(request, 'chest_number.html', context)

@login_required
def all_green_room_lists(request):
    """Show Green Room List (sign sheet) for ALL programs as HTML"""
    user = request.user

    programs = Program.objects.all().select_related('category').order_by('category__name', 'name')
    program_participants = []

    for program in programs:
        participants = Contestant.objects.filter(
            participation__program=program
        ).select_related('team', 'category').order_by('chest_no')

        # Filter by team if user belongs to a team
        if hasattr(user, 'team'):
            participants = participants.filter(team=user.team)

        program_participants.append({
            'program': program,
            'participants': participants
        })

    context = {
        'program_participants': program_participants,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }
    return render(request, 'all_green_room_list.html', context)

@login_required
def download_all_green_room_pdf(request):
    """Download Green Room Lists for all programs as PDF"""
    user = request.user

    # Fetch programs ordered by category, then program name
    programs = Program.objects.all().select_related('category').order_by('category__name', 'name')

    program_participants = []
    for program in programs:
        participants = Contestant.objects.filter(
            participation__program=program
        ).select_related('team', 'category').order_by('chest_no')

        # Filter by team if team user
        if hasattr(user, 'team'):
            participants = participants.filter(team=user.team)

        program_participants.append({
            'program': program,
            'participants': participants
        })

    # Filename
    if hasattr(user, 'team'):
        filename = f"all_green_room_{user.team.name}.pdf"
    else:
        filename = "all_green_room.pdf"

    # Render template
    template_path = 'all_green_room_pdf.html'
    context = {
        'program_participants': program_participants,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response



@login_required
def download_all_valuation_forms_pdf(request):
    """Download Valuation Form PDF for ALL programs"""
    user = request.user

    programs = Program.objects.all().order_by('name')
    program_participants = []

    for program in programs:
        participants = Contestant.objects.filter(
            participation__program=program
        ).select_related('team', 'category').order_by('chest_no')

        # Filter by team if user belongs to a team
        if hasattr(user, 'team'):
            participants = participants.filter(team=user.team)

        program_participants.append({
            'program': program,
            'participants': participants
        })

    # File name
    if hasattr(user, 'team'):
        filename = f"all_programs_{user.team.name}_valuation.pdf"
    else:
        filename = "all_programs_valuation.pdf"

    template_path = 'all_valuation_forms.html'  # New template
    context = {
        'program_participants': program_participants,
        'is_team_user': hasattr(user, 'team'),
        'team_name': user.team.name if hasattr(user, 'team') else None
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')

    return response


from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
from .models import Contestant

def download_chest_cards_pdf(request):
    """Download Chest Cards PDF for all contestants"""
    contestants = Contestant.objects.all().order_by('chest_no')

    template_path = 'chest_cards_pdf.html'
    context = {'contestants': contestants}

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="chest_cards.pdf"'

    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Error while generating PDF <pre>' + html + '</pre>')
    return response


from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
import io

def assigned_programs_pdf(request):
    team_id = request.GET.get('team')
    category_id = request.GET.get('category')

    participations = Participation.objects.all()
    if team_id:
        participations = participations.filter(contestant__team_id=team_id)
    if category_id:
        participations = participations.filter(contestant__category_id=category_id)

    template_path = 'assigned_programs_pdf.html'
    context = {
        'participations': participations,
    }

    # Render HTML
    template = get_template(template_path)
    html = template.render(context)

    # Create PDF
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="assigned_programs.pdf"'
    pisa.CreatePDF(io.BytesIO(html.encode("UTF-8")), dest=response, encoding='UTF-8')

    return response


from django.contrib import messages
from django.db.models import Q
from django.db import transaction
from .models import (
    Program, Contestant, Team, GroupParticipation, 
    Participation, PointsConfig
)

# ----------------- Group Program Management -----------------

def create_group_participation(request):
    """Create a new group participation"""
    if request.method == 'POST':
        program_id = request.POST.get('program_id')
        contestant_ids = request.POST.getlist('contestants')
        group_name = request.POST.get('group_name', '')
        
        try:
            with transaction.atomic():
                program = get_object_or_404(Program, id=program_id, is_group=True)
                
                # Validate contestant count
                if len(contestant_ids) < program.min_participants or len(contestant_ids) > program.max_participants:
                    messages.error(request, 
                        f"Number of participants must be between {program.min_participants} "
                        f"and {program.max_participants}")
                    return redirect('group_participation_form')
                
                # Get contestants and validate they're from the same team
                contestants = Contestant.objects.filter(id__in=contestant_ids)
                teams = set(c.team for c in contestants)
                
                if len(teams) > 1:
                    messages.error(request, "All contestants must be from the same team")
                    return redirect('group_participation_form')
                
                team = list(teams)[0]
                
                # Check if this team already has a group for this program
                existing_group = GroupParticipation.objects.filter(
                    program=program, team=team
                ).first()
                
                if existing_group:
                    messages.error(request, f"Team {team.name} already has a group for {program.name}")
                    return redirect('group_participation_form')
                
                # Create group participation
                group_participation = GroupParticipation.objects.create(
                    program=program,
                    team=team,
                    group_name=group_name
                )
                group_participation.contestants.set(contestants)
                
                messages.success(request, f"Group created successfully for {program.name}")
                return redirect('group_participation_list')
                
        except Exception as e:
            messages.error(request, f"Error creating group: {str(e)}")
            return redirect('group_participation_form')
    
    # GET request - show form
    programs = Program.objects.filter(is_group=True)
    teams = Team.objects.all()
    contestants = Contestant.objects.all().select_related('team')
    
    context = {
        'programs': programs,
        'teams': teams,
        'contestants': contestants,
    }
    return render(request, 'group_participation_form.html', context)

def group_participation_list(request):
    """List all group participations"""
    group_participations = GroupParticipation.objects.all().select_related(
        'program', 'team'
    ).prefetch_related('contestants')
    
    context = {
        'group_participations': group_participations
    }
    return render(request, 'group_participation_list.html', context)

def add_group_marks(request, group_id):
    """Add marks to a group participation"""
    group_participation = get_object_or_404(GroupParticipation, id=group_id)
    
    if request.method == 'POST':
        marks = request.POST.get('marks')
        
        try:
            marks = int(marks)
            if marks < 0 or marks > 100:
                messages.error(request, "Marks must be between 0 and 100")
                return redirect('add_group_marks', group_id=group_id)
            
            group_participation.marks = marks
            group_participation.save()
            
            # Calculate grade
            calculate_group_grades_and_points()
            
            messages.success(request, f"Marks added successfully for {group_participation}")
            return redirect('group_participation_list')
            
        except ValueError:
            messages.error(request, "Please enter valid marks")
            return redirect('add_group_marks', group_id=group_id)
    
    context = {
        'group_participation': group_participation
    }
    return render(request, 'add_group_marks.html', context)

# ----------------- Points Calculation Functions -----------------

def calculate_group_grades_and_points():
    """Calculate grades, ranks, and points for all group participations"""
    config = PointsConfig.get_config()
    
    # Get all programs that have group participations with marks
    programs_with_groups = Program.objects.filter(
        groupparticipation__marks__isnull=False,
        is_group=True
    ).distinct()
    
    for program in programs_with_groups:
        # Get all group participations for this program with marks
        group_participations = GroupParticipation.objects.filter(
            program=program,
            marks__isnull=False
        ).order_by('-marks')  # Order by marks descending
        
        # Calculate ranks
        current_rank = 1
        previous_marks = None
        rank_increment = 1
        
        for i, group in enumerate(group_participations):
            if previous_marks is not None and group.marks < previous_marks:
                current_rank += rank_increment
                rank_increment = 1
            elif previous_marks is not None and group.marks == previous_marks:
                rank_increment += 1
            
            group.rank = current_rank
            previous_marks = group.marks
            
            # Calculate grade based on marks
            if group.marks >= config.grade_a_threshold:
                group.grade = 'A'
            elif group.marks >= config.grade_b_threshold:
                group.grade = 'B'
            elif group.marks >= config.grade_c_threshold:
                group.grade = 'C'
            else:
                group.grade = 'D'
            
            group.save()
    
    # Calculate and award points
    award_group_points()

def award_group_points():
    """Award points to teams based on group participations"""
    config = PointsConfig.get_config()
    
    # Reset points_awarded flag for recalculation
    GroupParticipation.objects.filter(points_awarded=True).update(points_awarded=False)
    
    group_participations = GroupParticipation.objects.filter(
        marks__isnull=False,
        points_awarded=False
    )
    
    for group in group_participations:
        points = 0
        
        # Rank-based points
        if group.rank == 1:
            points += config.rank_1_points
        elif group.rank == 2:
            points += config.rank_2_points
        elif group.rank == 3:
            points += config.rank_3_points
        
        # Grade-based points
        if group.grade == 'A':
            points += config.grade_a_points
        elif group.grade == 'B':
            points += config.grade_b_points
        elif group.grade == 'C':
            points += config.grade_c_points
        
        # Add points to team
        if points > 0:
            group.team.total_points += points
            group.team.save()
            
            # Mark as points awarded
            group.points_awarded = True
            group.save()

def recalculate_all_team_points():
    """Recalculate total points for all teams (both individual and group)"""
    # Reset all team points
    Team.objects.update(total_points=0)
    
    # Reset points awarded flags
    Participation.objects.update(points_awarded=False)
    GroupParticipation.objects.update(points_awarded=False)
    
    # Recalculate individual participations
    calculate_individual_grades_and_points()  # You need to implement this
    
    # Recalculate group participations
    calculate_group_grades_and_points()

def calculate_individual_grades_and_points():
    """Calculate grades, ranks, and points for individual participations"""
    # This is your existing function for individual programs
    # You should implement this similar to group calculation
    config = PointsConfig.get_config()
    
    programs_with_individual = Program.objects.filter(
        participation__marks__isnull=False,
        is_group=False
    ).distinct()
    
    for program in programs_with_individual:
        participations = Participation.objects.filter(
            program=program,
            marks__isnull=False
        ).order_by('-marks')
        
        # Similar ranking logic as group
        current_rank = 1
        previous_marks = None
        rank_increment = 1
        
        for i, participation in enumerate(participations):
            if previous_marks is not None and participation.marks < previous_marks:
                current_rank += rank_increment
                rank_increment = 1
            elif previous_marks is not None and participation.marks == previous_marks:
                rank_increment += 1
            
            participation.rank = current_rank
            previous_marks = participation.marks
            
            # Calculate grade
            if participation.marks >= config.grade_a_threshold:
                participation.grade = 'A'
            elif participation.marks >= config.grade_b_threshold:
                participation.grade = 'B'
            elif participation.marks >= config.grade_c_threshold:
                participation.grade = 'C'
            else:
                participation.grade = 'D'
            
            participation.save()
    
    # Award individual points
    award_individual_points()

def award_individual_points():
    """Award points to teams based on individual participations"""
    config = PointsConfig.get_config()
    
    participations = Participation.objects.filter(
        marks__isnull=False,
        points_awarded=False
    )
    
    for participation in participations:
        points = 0
        
        # Rank-based points
        if participation.rank == 1:
            points += config.rank_1_points
        elif participation.rank == 2:
            points += config.rank_2_points
        elif participation.rank == 3:
            points += config.rank_3_points
        
        # Grade-based points
        if participation.grade == 'A':
            points += config.grade_a_points
        elif participation.grade == 'B':
            points += config.grade_b_points
        elif participation.grade == 'C':
            points += config.grade_c_points
        
        # Add points to contestant's team
        if points > 0:
            participation.contestant.team.total_points += points
            participation.contestant.team.save()
            
            # Also add to contestant's individual points
            participation.contestant.total_points += points
            participation.contestant.save()
            
            # Mark as points awarded
            participation.points_awarded = True
            participation.save()

# ----------------- Leaderboard Views -----------------

def team_leaderboard2(request):
    """Display team leaderboard"""
    teams = Team.objects.all().order_by('-total_points')
    
    context = {
        'teams': teams
    }
    return render(request, 'competition/team_leaderboard.html', context)

def program_results(request, program_id):
    """Display results for a specific program (individual or group)"""
    program = get_object_or_404(Program, id=program_id)
    
    if program.is_group:
        results = GroupParticipation.objects.filter(
            program=program,
            marks__isnull=False
        ).order_by('rank').select_related('team').prefetch_related('contestants')
        template = 'competition/group_program_results.html'
    else:
        results = Participation.objects.filter(
            program=program,
            marks__isnull=False
        ).order_by('rank').select_related('contestant', 'contestant__team')
        template = 'competition/individual_program_results.html'
    
    context = {
        'program': program,
        'results': results
    }
    return render(request, template, context)

# Additional view for recalculating points
def recalculate_points_view(request):
    """Manual recalculation of all points"""
    if request.method == 'POST':
        try:
            from .views import recalculate_all_team_points
            recalculate_all_team_points()
            messages.success(request, "All team points have been recalculated successfully!")
        except Exception as e:
            messages.error(request, f"Error recalculating points: {str(e)}")
    
    return redirect('team_leaderboard')

@login_required
def contestant_points_list(request):
    # Only Junior and Senior contestants
    contestants = Contestant.objects.filter(
        category__name__in=["JUNIOR", "SENIOR"]
    ).distinct()

    contestant_results = []

    for contestant in contestants:
        # Exclude group programs and general programs
        participations = Participation.objects.filter(
            contestant=contestant,
            marks__isnull=False
        ).exclude(
            program__is_group=True
        ).exclude(
            program__category__name__iexact="GENERAL"
        ).select_related("program", "program__category")

        total_points = 0
        program_details = []

        for p in participations:
            # Individual point system only
            rank_points_dict = POINTS_FOR_RANK
            grade_points_dict = POINTS_FOR_GRADE

            rank_points = rank_points_dict.get(p.rank, 0)
            grade_points = grade_points_dict.get(p.grade, 0) if p.grade else 0
            total = rank_points + grade_points if p.points_awarded else 0

            total_points += total

            program_details.append({
                "program_name": p.program.name,
                "program_category": p.program.category.name,
                "rank": p.rank,
                "grade": p.grade,
                "rank_points": rank_points,
                "grade_points": grade_points,
                "total_points": total
            })

        if program_details:
            contestant_results.append({
                "contestant": contestant,
                "programs": program_details,
                "total_points": total_points
            })

    # Sort by total points descending
    contestant_results.sort(key=lambda x: x["total_points"], reverse=True)

    return render(request, "contestant_points.html", {
        "contestant_results": contestant_results
    })

def results_page(request):
    return render (request, 'results_page.html')

from django.shortcuts import render
from .models import Contestant, Category, Program

@login_required
def contestant_programs(request):
    user = request.user

    if hasattr(user, "team"):  # if user is a team user
        contestants = Contestant.objects.filter(team=user.team).prefetch_related(
            "participation_set__program__category"
        )
        is_team_user = True
        team_name = user.team.name
    else:  # committee/admin etc.
        contestants = Contestant.objects.prefetch_related(
            "participation_set__program__category"
        )
        is_team_user = False
        team_name = None

    context = {
        "contestants": contestants,
        "is_team_user": is_team_user,
        "team_name": team_name,
    }
    return render(request, "contestant_programs.html", context)

@login_required
def contestant_programs_pdf_xml(request):
    """
    Generate PDF using xhtml2pdf (pisa).
    Team users see only their team's contestants.
    """
    user = request.user
    is_team_user = hasattr(user, "team")

    if is_team_user:
        contestants = Contestant.objects.filter(team=user.team).prefetch_related(
            "participation_set__program__category"
        )
        team_name = user.team.name
    else:
        contestants = Contestant.objects.all().prefetch_related(
            "participation_set__program__category"
        )
        team_name = None

    context = {
        "contestants": contestants,
        "is_team_user": is_team_user,
        "team_name": team_name,
    }

    # Render HTML template to string
    template = get_template("contestant_programs_pdf_xml.html")
    html = template.render(context)

    # Create PDF
    result = io.BytesIO()
    pisa_status = pisa.CreatePDF(src=html, dest=result, encoding='utf-8')

    if pisa_status.err:
        # For debug you can return html, but in production give a friendly message
        return HttpResponse('We had some errors while generating PDF. Please check your template and CSS.')

    # Return PDF as response
    response = HttpResponse(result.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="contestant_programs.pdf"'
    return response

@login_required
def enter_marks_summary_cat(request):
    if request.user.role != 'admin':
        return redirect('dashboard_team')

    # Get filter parameters
    program_id = request.GET.get('program')
    category_id = request.GET.get('category')

    # Get all programs and categories for filter dropdowns
    programs = Program.objects.all().order_by('name')
    categories = Category.objects.all().order_by('name')

    # Base queryset
    participations = Participation.objects.filter(marks__isnull=False)

    # Apply filters
    if program_id:
        participations = participations.filter(program_id=program_id)
    if category_id:
        participations = participations.filter(contestant__category_id=category_id)

    # Optimize query
    participations = participations.select_related(
        'contestant__team', 'contestant__category', 'program'
    ).order_by('program__name', '-marks')

    # Handle selected objects
    selected_program = Program.objects.get(id=program_id) if program_id else None
    selected_category = Category.objects.get(id=category_id) if category_id else None

    # Ranking + grade assignment logic (same as before) ...
    # You can reuse your ranking & points awarding logic here

    return render(request, 'enter_marks_summary_cat.html', {
        'participations': participations,
        'programs': programs,
        'categories': categories,
        'selected_program': selected_program,
        'selected_category': selected_category,
        'program_id': program_id,
        'category_id': category_id,
    })
