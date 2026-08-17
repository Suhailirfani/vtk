from datetime import datetime, time, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Max
from core.models import Program, FestDay, Stage, ProgramSchedule
from core.schedule_utils import (
    get_program_assigned_count,
    calculate_program_duration,
    detect_all_clashes,
    generate_smart_auto_schedule,
    recalculate_stage_schedules
)

@login_required
def manage_schedule(request):
    if request.user.role != 'admin':
        messages.error(request, "Access denied. Admin privileges required.")
        return redirect('face_page')

    import json

    fest_days = FestDay.objects.all().order_by('day_number')
    stages = Stage.objects.all().order_by('stage_type', 'name')
    programs = Program.objects.select_related('category', 'preferred_stage', 'schedule', 'schedule__fest_day', 'schedule__stage').all()

    # Build info map of schedules per (fest_day_id, stage_id) containing count and next_start_time
    stage_info_map = {}
    base_date = datetime.today().date()
    for day in fest_days:
        for st in stages:
            schedules = ProgramSchedule.objects.filter(fest_day=day, stage=st).order_by('order', 'end_time')
            cnt = schedules.count()
            last_sched = schedules.last()
            if last_sched:
                last_end_dt = datetime.combine(base_date, last_sched.end_time)
                next_start_time = (last_end_dt + timedelta(minutes=1)).time().strftime('%H:%M')
            else:
                next_start_time = day.start_time.strftime('%H:%M')

            stage_info_map[f"{day.id}_{st.id}"] = {
                'count': cnt,
                'next_start_time': next_start_time
            }

    # Pre-calculate assigned counts, duration, and default stage/order for each program
    program_list = []
    scheduled_count = 0
    first_day_id = fest_days.first().id if fest_days.exists() else None

    for p in programs:
        assigned_count = get_program_assigned_count(p)
        calc_dur = calculate_program_duration(p)
        has_sched = hasattr(p, 'schedule') and p.schedule is not None
        if has_sched:
            scheduled_count += 1

        # Determine default stage, order & start time
        if has_sched:
            default_stage_id = p.schedule.stage_id
            default_fest_day_id = p.schedule.fest_day_id
            default_order = p.schedule.order
            default_start_time = p.schedule.start_time.strftime('%H:%M')
        elif p.preferred_stage_id:
            default_stage_id = p.preferred_stage_id
            default_fest_day_id = first_day_id
            st_info = stage_info_map.get(f"{default_fest_day_id}_{default_stage_id}", {'count': 0, 'next_start_time': '09:00'})
            default_order = st_info['count'] + 1
            default_start_time = st_info['next_start_time']
        else:
            suitable_stage = next((st for st in stages if st.stage_type == p.program_type), None)
            if not suitable_stage and stages.exists():
                suitable_stage = stages.first()
            default_stage_id = suitable_stage.id if suitable_stage else None
            default_fest_day_id = first_day_id
            st_info = stage_info_map.get(f"{default_fest_day_id}_{default_stage_id}", {'count': 0, 'next_start_time': '09:00'}) if (default_fest_day_id and default_stage_id) else {'count': 0, 'next_start_time': '09:00'}
            default_order = st_info['count'] + 1
            default_start_time = st_info['next_start_time']

        program_list.append({
            'program': p,
            'assigned_count': assigned_count,
            'calculated_duration': calc_dur,
            'has_schedule': has_sched,
            'schedule': p.schedule if has_sched else None,
            'default_stage_id': default_stage_id,
            'default_fest_day_id': default_fest_day_id,
            'default_order': default_order,
            'default_start_time': default_start_time
        })

    clash_data = detect_all_clashes()

    # Master timetable matrix grouped by FestDay and Stage
    timetable_by_day = []
    for day in fest_days:
        day_stages = []
        for stage in stages:
            schedules = ProgramSchedule.objects.filter(fest_day=day, stage=stage).select_related('program', 'program__category').order_by('order', 'start_time')
            day_stages.append({
                'stage': stage,
                'schedules': schedules
            })
        timetable_by_day.append({
            'day': day,
            'stages': day_stages
        })

    context = {
        'fest_days': fest_days,
        'stages': stages,
        'program_list': program_list,
        'total_programs': len(programs),
        'scheduled_count': scheduled_count,
        'clash_data': clash_data,
        'timetable_by_day': timetable_by_day,
        'stage_info_json': json.dumps(stage_info_map)
    }
    return render(request, 'manage_schedule.html', context)

@login_required
def add_fest_day(request):
    if request.user.role != 'admin' or request.method != 'POST':
        return redirect('manage_schedule')

    day_number = request.POST.get('day_number')
    date_str = request.POST.get('date')
    name = request.POST.get('name', '').strip()
    start_time_str = request.POST.get('start_time', '09:00')
    end_time_str = request.POST.get('end_time', '21:00')

    if day_number:
        parsed_date = None
        if date_str:
            try:
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        try:
            st_time = datetime.strptime(start_time_str, '%H:%M').time()
        except ValueError:
            st_time = time(9, 0)

        try:
            en_time = datetime.strptime(end_time_str, '%H:%M').time()
        except ValueError:
            en_time = time(21, 0)
        
        FestDay.objects.get_or_create(
            day_number=int(day_number),
            defaults={'date': parsed_date, 'name': name, 'start_time': st_time, 'end_time': en_time}
        )
        messages.success(request, f"Fest Day {day_number} added successfully!")

    return redirect('manage_schedule')

@login_required
def delete_fest_day(request, day_id):
    if request.user.role != 'admin' or request.method != 'POST':
        return redirect('manage_schedule')

    day = get_object_or_404(FestDay, id=day_id)
    day_num = day.day_number
    day.delete()
    messages.success(request, f"Fest Day {day_num} deleted.")
    return redirect('manage_schedule')

@login_required
def add_stage(request):
    if request.user.role != 'admin' or request.method != 'POST':
        return redirect('manage_schedule')

    name = request.POST.get('name', '').strip()
    stage_type = request.POST.get('stage_type', 'STAGE')
    location_details = request.POST.get('location_details', '').strip()

    if name:
        Stage.objects.create(
            name=name,
            stage_type=stage_type,
            location_details=location_details
        )
        messages.success(request, f"Venue '{name}' ({stage_type}) added successfully!")

    return redirect('manage_schedule')

@login_required
def delete_stage(request, stage_id):
    if request.user.role != 'admin' or request.method != 'POST':
        return redirect('manage_schedule')

    stage = get_object_or_404(Stage, id=stage_id)
    st_name = stage.name
    stage.delete()
    messages.success(request, f"Venue '{st_name}' deleted.")
    return redirect('manage_schedule')

@login_required
def update_program_duration(request, program_id):
    if request.user.role != 'admin' or request.method != 'POST':
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
            return JsonResponse({'status': 'error', 'message': 'Access denied'}, status=403)
        return redirect('manage_schedule')

    program = get_object_or_404(Program, id=program_id)
    program_type = request.POST.get('program_type', 'STAGE')
    presentation_mode = request.POST.get('presentation_mode', 'SEQUENTIAL')
    dur_per_part = request.POST.get('duration_per_participant', '5')
    buffer_mins = request.POST.get('buffer_margin_minutes', '0')
    preferred_stage_id = request.POST.get('preferred_stage_id', '')

    program.program_type = program_type
    program.presentation_mode = presentation_mode
    program.duration_per_participant = max(int(dur_per_part), 1)
    program.buffer_margin_minutes = max(int(buffer_mins), 0)

    if preferred_stage_id:
        program.preferred_stage_id = int(preferred_stage_id)
    else:
        program.preferred_stage = None

    program.save()

    calc_dur = calculate_program_duration(program)
    
    # Update active schedule end_time & total_duration_minutes if schedule exists
    if hasattr(program, 'schedule') and program.schedule is not None:
        sched = program.schedule
        recalculate_stage_schedules(sched.fest_day, sched.stage)

    clash_data = detect_all_clashes()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
        return JsonResponse({
            'status': 'success',
            'program_id': program.id,
            'program_name': program.name,
            'calculated_duration': calc_dur,
            'total_clashes': clash_data['total_clash_count']
        })

    messages.success(request, f"Schedule settings for '{program.name}' updated.")
    return redirect('manage_schedule')

@login_required
def save_program_schedule(request):
    if request.user.role != 'admin' or request.method != 'POST':
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
            return JsonResponse({'status': 'error', 'message': 'Access denied'}, status=403)
        return redirect('manage_schedule')

    program_id = request.POST.get('program_id')
    fest_day_id = request.POST.get('fest_day_id')
    stage_id = request.POST.get('stage_id')
    order_val = request.POST.get('order')
    start_time_str = request.POST.get('start_time')

    if program_id and fest_day_id and stage_id:
        program = get_object_or_404(Program, id=program_id)
        fest_day = get_object_or_404(FestDay, id=fest_day_id)
        stage = get_object_or_404(Stage, id=stage_id)

        old_day = None
        old_stage = None
        if hasattr(program, 'schedule') and program.schedule is not None:
            old_day = program.schedule.fest_day
            old_stage = program.schedule.stage

        # Determine target order
        if order_val and str(order_val).isdigit():
            target_order = int(order_val)
        else:
            if hasattr(program, 'schedule') and program.schedule is not None and program.schedule.fest_day_id == fest_day.id and program.schedule.stage_id == stage.id:
                target_order = program.schedule.order
            else:
                max_ord = ProgramSchedule.objects.filter(fest_day=fest_day, stage=stage).aggregate(Max('order'))['order__max']
                target_order = (max_ord or 0) + 1

        calc_mins = calculate_program_duration(program)

        if start_time_str:
            try:
                start_t = datetime.strptime(start_time_str, '%H:%M').time()
            except ValueError:
                start_t = fest_day.start_time
        else:
            start_t = fest_day.start_time

        end_t = (datetime.combine(datetime.today(), start_t) + timedelta(minutes=calc_mins)).time()

        sched, created = ProgramSchedule.objects.update_or_create(
            program=program,
            defaults={
                'fest_day': fest_day,
                'stage': stage,
                'order': target_order,
                'start_time': start_t,
                'end_time': end_t,
                'total_duration_minutes': calc_mins
            }
        )

        recalculate_stage_schedules(fest_day, stage)
        if old_day and old_stage and (old_day.id != fest_day.id or old_stage.id != stage.id):
            recalculate_stage_schedules(old_day, old_stage)

        sched.refresh_from_db()
        clash_data = detect_all_clashes()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
            slot_text = f"Day {fest_day.day_number} @ {stage.name} (#{sched.order}: {sched.start_time.strftime('%I:%M %p')} - {sched.end_time.strftime('%I:%M %p')})"
            return JsonResponse({
                'status': 'success',
                'program_id': program.id,
                'schedule_id': sched.id,
                'order': sched.order,
                'slot_text': slot_text,
                'total_clashes': clash_data['total_clash_count']
            })

        messages.success(request, f"Schedule saved for '{program.name}'.")

    return redirect('manage_schedule')

@login_required
def delete_program_schedule(request, schedule_id):
    if request.user.role != 'admin' or request.method != 'POST':
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
            return JsonResponse({'status': 'error', 'message': 'Access denied'}, status=403)
        return redirect('manage_schedule')

    sched = get_object_or_404(ProgramSchedule, id=schedule_id)
    prog_id = sched.program_id
    prog_name = sched.program.name
    old_day = sched.fest_day
    old_stage = sched.stage
    sched.delete()

    recalculate_stage_schedules(old_day, old_stage)
    clash_data = detect_all_clashes()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
        return JsonResponse({
            'status': 'success',
            'program_id': prog_id,
            'total_clashes': clash_data['total_clash_count']
        })

    messages.success(request, f"Schedule for '{prog_name}' removed.")
    return redirect('manage_schedule')

@login_required
def reorder_program_schedule(request, schedule_id):
    if request.user.role != 'admin' or request.method != 'POST':
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
            return JsonResponse({'status': 'error', 'message': 'Access denied'}, status=403)
        return redirect('manage_schedule')

    sched = get_object_or_404(ProgramSchedule, id=schedule_id)
    direction = request.POST.get('direction')

    schedules = list(ProgramSchedule.objects.filter(fest_day=sched.fest_day, stage=sched.stage).order_by('order', 'start_time', 'id'))

    current_idx = None
    for idx, s in enumerate(schedules):
        if s.id == sched.id:
            current_idx = idx
            break

    if current_idx is not None:
        if direction == 'up' and current_idx > 0:
            schedules[current_idx], schedules[current_idx - 1] = schedules[current_idx - 1], schedules[current_idx]
        elif direction == 'down' and current_idx < len(schedules) - 1:
            schedules[current_idx], schedules[current_idx + 1] = schedules[current_idx + 1], schedules[current_idx]

        for i, s in enumerate(schedules, start=1):
            s.order = i
            s.save(update_fields=['order'])

        recalculate_stage_schedules(sched.fest_day, sched.stage)

    clash_data = detect_all_clashes()

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
        return JsonResponse({
            'status': 'success',
            'total_clashes': clash_data['total_clash_count']
        })

    messages.success(request, f"Reordered schedule for '{sched.program.name}'.")
    return redirect('manage_schedule')

@login_required
def run_auto_scheduler(request):
    if request.user.role != 'admin' or request.method != 'POST':
        return redirect('manage_schedule')

    res = generate_smart_auto_schedule()

    if 'error' in res:
        messages.error(request, res['error'])
    else:
        sched_count = res.get('scheduled_count', 0)
        skip_count = res.get('skipped_count', 0)
        messages.success(request, f"Smart Auto-Scheduler completed! Successfully scheduled {sched_count} programs.")
        if skip_count > 0:
            messages.warning(request, f"Could not fit {skip_count} programs into available time slots. Consider adding another fest day/stage or extending operating hours.")

    return redirect('manage_schedule')

    if 'error' in res:
        messages.error(request, res['error'])
    else:
        sched_count = res.get('scheduled_count', 0)
        skip_count = res.get('skipped_count', 0)
        messages.success(request, f"Auto-Scheduler completed! Successfully scheduled {sched_count} programs.")
        if skip_count > 0:
            messages.warning(request, f"Could not fit {skip_count} programs into available time slots. Consider adding another fest day/stage or extending hours.")

    return redirect('manage_schedule')

@login_required
def clear_all_schedules(request):
    if request.user.role != 'admin' or request.method != 'POST':
        return redirect('manage_schedule')

    count = ProgramSchedule.objects.count()
    ProgramSchedule.objects.all().delete()
    messages.success(request, f"Cleared all {count} program schedules.")
    return redirect('manage_schedule')

@login_required
def view_clashes(request):
    if request.user.role != 'admin':
        messages.error(request, "Access denied. Admin privileges required.")
        return redirect('face_page')

    clash_data = detect_all_clashes()
    return render(request, 'view_clashes.html', {'clash_data': clash_data})
