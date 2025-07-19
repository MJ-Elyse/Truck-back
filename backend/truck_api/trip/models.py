from django.db import models
from datetime import datetime, timedelta, time, timezone
from django.db import transaction
from django.db.models import Max

def timedelta_to_time(td):
    total_seconds = int(td.total_seconds())
    hours = (total_seconds // 3600) % 24
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return time(hour=hours, minute=minutes, second=seconds, microsecond=0)

class TripConfig(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey('users.user', on_delete=models.CASCADE)
    ways = models.JSONField(null=False)
    totaldistance = models.FloatField()
    total_time_driving = models.TimeField()
    datetimeUTC = models.DateTimeField()

    @classmethod
    def get_current_cycle_by_user_id(cls, user_id, plannedStartDate):
        try:
            trip_configs = cls.objects.filter(user_id = user_id).order_by('-id')

            if(trip_configs is None):
                return TripDriving.get_remaining_driving_time(user_id, None, plannedStartDate)    
            
            date_end_cycle = None
            for trip_config in trip_configs:
                date_end_cycle = TripBreak.get_rest_periods_time_begin(trip_config.id)
                if(date_end_cycle is not None):
                    break

            return TripDriving.get_remaining_driving_time(user_id, date_end_cycle, plannedStartDate)
        except Exception as e:
            raise e

    @classmethod
    def save_all(cls, user_id, front_data, datetimeUTC):
        with transaction.atomic():
            trip_config_id = TripConfig.save_trip_config(user_id, front_data, datetimeUTC)
            TripDriving.save_driving_from_front(trip_config_id, front_data.get("waypoints", {}), datetimeUTC)
            TripBreak.save_breaks_from_front(trip_config_id, front_data.get("waypoints", {}), datetimeUTC)
            if front_data.get("distance_to_dropoff"):   
                TripRefueling.save_refueling(trip_config_id, front_data.get("distance_to_dropoff"))

    @classmethod 
    def save_trip_config(cls, user_id, front_data, datetimeUTC):
        """
        Records TripBreaks from a list of steps sent from the front.
        :param user_id: ID of the linked User
        :param front_data: list of objects sent by the front
        """
        try:
            
            index = 0
            begin_drive = None 
            end_drive = None
            waypoints = front_data.get("waypoints", [])
            accumulated_timeDriving = 0
            accumulated_duration = 0
            for step in waypoints:
                last_point_duration = waypoints[index - 1].get("duration", [0])[0] if index > 0 else 0
                accumulated_duration += (step.get("duration_from_last_point", 0)) + last_point_duration
                duration_seconds = step.get("duration", [0])[0]

                if begin_drive is None: 
                    begin_drive = accumulated_duration + duration_seconds
                else:
                    end_drive = accumulated_duration
                    accumulated_timeDriving += (end_drive - begin_drive)
                    begin_drive = (end_drive + duration_seconds)
                    end_drive = None
                
                index+=1
            
            ttd = timedelta_to_time(timedelta(seconds=accumulated_timeDriving))
            obj = cls.objects.create(
                user_id = user_id,
                totaldistance = front_data.get("total_distance", 0),
                ways = front_data.get("waypoints", []),
                total_time_driving = ttd,
                datetimeUTC = datetimeUTC
            )
            return obj.id

        except Exception as e:
            raise e    

    class Meta:
        db_table = 'tripconfig'

class TripDriving(models.Model):
    id = models.AutoField(primary_key=True)
    tripconfig = models.ForeignKey('TripConfig', on_delete=models.CASCADE)
    time_total = models.TimeField(null=False)
    begin = models.DateTimeField(null=False)

    
    @classmethod
    def get_remaining_driving_time(cls, user_id, after_date, plannedStartDate):
        if user_id is None:
            return 11 * 3600, 8 * 3600
        
        try: 
            filters = {
                'tripconfig__user_id': user_id,
            }
            if after_date is not None:
                filters['begin__gte'] = after_date
            trip_drivings = cls.objects.filter(**filters).order_by('-begin')

            if after_date is None:
                after_date = TripConfig.objects.filter(user_id=user_id).aggregate(Max('datetimeUTC'))['datetimeUTC__max']

            if not trip_drivings.exists():
                return 11 * 3600, 8 * 3600  

            total_driving_time = timedelta()
            need_rest = None

            for trip in trip_drivings:
                total_driving_time += timedelta(
                    hours=trip.time_total.hour, 
                    minutes=trip.time_total.minute, 
                    seconds=trip.time_total.second
                )
                
            total_seconds = total_driving_time.total_seconds()

            if total_seconds <= 8 * 3600:
                need_rest = (8 * 3600) - total_seconds
            
            max_driving_seconds = 11 * 3600

            if(plannedStartDate < after_date + timedelta(seconds=total_seconds)):
                raise Exception(f"Invalid planned Date {plannedStartDate} {after_date + timedelta(seconds=total_seconds)}")

            if(plannedStartDate <= after_date + timedelta(seconds=total_seconds + 36000)):
                remaining_time = max_driving_seconds - total_seconds
            else:
                need_rest = 8 * 3600
                remaining_time = max_driving_seconds
            
            return int(remaining_time), int(need_rest) if need_rest is not None else None,
        
        except Exception as e:
            raise e
    
    @classmethod
    def save_driving_from_front(cls, tripconfig_id, front_data, datetimeUTC):
        """
        Records TripBreaks from a list of steps sent from the front.
        :param tripconfig_id: ID of the linked TripConfig
        :param front_data: list of objects sent by the front
        """
        try:
            trip_config = TripConfig.objects.get(id=tripconfig_id)
            index = 0
            begin_drive = None
            end_drive = None
            accumulated_duration = 0
            for step in front_data:
                last_point_duration = front_data[index - 1].get("duration", [0])[0] if index > 0 else 0
                accumulated_duration += (step.get("duration_from_last_point", 0)) + last_point_duration
                duration_seconds = step.get("duration", [0])[0]
                
                if begin_drive is None: 
                    begin_drive = accumulated_duration + duration_seconds
                else:
                    end_drive = accumulated_duration
                    total_drive = (end_drive - begin_drive)
                    cls.objects.create(
                        tripconfig=trip_config,
                        begin=(datetimeUTC + timedelta(seconds=(begin_drive))),
                        time_total=timedelta_to_time(timedelta(seconds=total_drive)),
                    )
                    begin_drive = (end_drive + duration_seconds)
                    end_drive = None
                
                index+=1

        except TripConfig.DoesNotExist:
            raise ValueError(f"TripConfig with id {tripconfig_id} does not exist")
        except Exception as e:
            raise e
    
    class Meta:
        db_table = 'tripdriving'


class TripBreak(models.Model):
    class ReasonChoices(models.TextChoices):
        REST = "rest", "Rest"
        REFUEL = "refuel", "Refuel"
        PICKUP = "pickup", "Pickup"
        DROPOFF = "dropoff", "Dropoff"

    id = models.AutoField(primary_key=True)
    tripconfig = models.ForeignKey('TripConfig', on_delete=models.CASCADE)
    begin = models.DateTimeField(null=False)
    end = models.DateTimeField(null=False)
    reason = models.CharField(max_length=10, choices=ReasonChoices.choices)

    @classmethod
    def get_rest_periods_time_begin(cls, tripconfig_id):
        try:
            trip_breaks = cls.objects.filter(tripconfig_id = tripconfig_id).order_by('-id') 
            total_rest_period = 0
            for trip_break in trip_breaks:
                duration = (trip_break.end - trip_break.begin).total_seconds()
                if(duration >= 7200):
                    total_rest_period += duration
                
                if(total_rest_period >= 36000):
                    return trip_break.end
            
            return None
        except Exception as e:
            raise e
        
    @classmethod
    def save_breaks_from_front(cls, tripconfig_id, front_data, datetimeUTC):
        """
        Records TripBreaks from a list of steps sent from the front.
        :param tripconfig_id: ID of the linked TripConfig
        :param front_data: list of objects sent by the front
        """
        try:
            trip_config = TripConfig.objects.get(id=tripconfig_id)
            index = 0
            accumulated_duration = 0
            for step in front_data:
                last_point_duration = front_data[index - 1].get("duration", [0])[0] if index > 0 else 0
                accumulated_duration += (step.get("duration_from_last_point", 0)) + last_point_duration
                duration_seconds = step.get("duration", [0])[0]
                label = step.get("label", "").lower()

                if any(reason in label for reason in ["rest", "refuel", "pickup", "dropoff"]):

                    if "rest" in label:
                        reason = cls.ReasonChoices.REST
                    elif "refuel" in label:
                        reason = cls.ReasonChoices.REFUEL
                    elif "pickup" in label:
                        reason = cls.ReasonChoices.PICKUP
                    elif "dropoff" in label:
                        reason = cls.ReasonChoices.DROPOFF
                    else:
                        continue

                    cls.objects.create(
                        tripconfig=trip_config,
                        begin=(datetimeUTC + timedelta(seconds=accumulated_duration)),
                        end=(datetimeUTC + timedelta(seconds=(accumulated_duration + duration_seconds))),
                        reason=reason
                    )
                
                index+=1

        except TripConfig.DoesNotExist:
            raise ValueError(f"TripConfig with id {tripconfig_id} does not exist")
        except Exception as e:
            raise e

    class Meta:
        db_table = 'tripbreak'


class TripRefueling(models.Model):
    id = models.AutoField(primary_key=True)
    tripconfig = models.ForeignKey('TripConfig', on_delete=models.CASCADE)
    distancetodropoff = models.FloatField()
    
    @classmethod
    def save_refueling(cls, tripconfig_id, distancetodropoff):
        try:
            trip_config = TripConfig.objects.get(id=tripconfig_id)
            refueling = cls.objects.create(
                tripconfig=trip_config,
                distancetodropoff=distancetodropoff
            )
            return refueling
        except TripConfig.DoesNotExist:
            raise ValueError(f"TripConfig with id {tripconfig_id} does not exist")
        except Exception as e:
            raise e

    @classmethod
    def get_total_distance_after_last_refueling(cls, user_id):
        
        try:
            last_refueling = cls.objects.filter(tripconfig__user_id=user_id).order_by('-tripconfig_id').first()

            if not last_refueling:
                return sum(TripConfig.objects.filter(user_id=user_id).values_list('totaldistance', flat=True))

            distance_from_last_refueling = last_refueling.distancetodropoff

            total_distance_after_refueling = sum(
                TripConfig.objects.filter(user_id=user_id, id__gt=last_refueling.tripconfig_id)
                .values_list('totaldistance', flat=True)
            )

            return distance_from_last_refueling + total_distance_after_refueling

        except Exception as e:
            raise e
    class Meta:
        db_table = 'triprefueling'