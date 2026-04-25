//go:build no_memcache

package reservation

import (
	"context"
	"errors"
	"time"

	pb "github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/services/reservation/proto"
	"github.com/opentracing/opentracing-go"
	"github.com/rs/zerolog/log"
	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/mongo"
)

var getCapacityFromMongo = func(ctx context.Context, client *mongo.Client, hotelId string) (int, bool, error) {
	collection := client.Database("reservation-db").Collection("number")

	mongoSpan, _ := opentracing.StartSpanFromContext(ctx, "mongodb_capacity_get_number")
	mongoSpan.SetTag("span.kind", "client")
	defer mongoSpan.Finish()

	var num number
	if err := collection.FindOne(ctx, bson.D{{"hotelId", hotelId}}).Decode(&num); err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return 0, false, nil
		}
		return 0, false, err
	}
	return num.Number, true, nil
}

var countReservationsFromMongo = func(ctx context.Context, client *mongo.Client, hotelId string, indate string, outdate string) (int, error) {
	collection := client.Database("reservation-db").Collection("reservation")
	filter := bson.D{{"hotelId", hotelId}, {"inDate", indate}, {"outDate", outdate}}

	mongoSpan, _ := opentracing.StartSpanFromContext(ctx, "mongodb_reservation_get_number")
	mongoSpan.SetTag("span.kind", "client")
	defer mongoSpan.Finish()

	curr, err := collection.Find(ctx, filter)
	if err != nil {
		return 0, err
	}
	defer curr.Close(ctx)

	var reserve []reservation
	if err := curr.All(ctx, &reserve); err != nil {
		return 0, err
	}

	count := 0
	for _, r := range reserve {
		count += r.Number
	}
	return count, nil
}

var insertReservationToMongo = func(ctx context.Context, client *mongo.Client, r reservation) error {
	collection := client.Database("reservation-db").Collection("reservation")
	_, err := collection.InsertOne(ctx, r)
	return err
}

// MakeReservation makes a reservation using MongoDB directly.
func (s *Server) MakeReservation(ctx context.Context, req *pb.Request) (*pb.Result, error) {
	res := &pb.Result{HotelId: make([]string, 0)}
	if len(req.HotelId) == 0 {
		return res, nil
	}

	hotelId := req.HotelId[0]
	if available, err := s.isHotelAvailable(ctx, hotelId, req.InDate, req.OutDate, int(req.RoomNumber)); err != nil {
		return nil, err
	} else if !available {
		return res, nil
	}

	if err := forEachNight(req.InDate, req.OutDate, func(indate string, outdate string) error {
		err := insertReservationToMongo(ctx, s.MongoClient, reservation{
			HotelId:      hotelId,
			CustomerName: req.CustomerName,
			InDate:       indate,
			OutDate:      outdate,
			Number:       int(req.RoomNumber),
		})
		if err != nil {
			log.Error().Msgf("Tried to insert hotel [hotelId %v], but got error %v", hotelId, err)
		}
		return err
	}); err != nil {
		return nil, err
	}

	res.HotelId = append(res.HotelId, hotelId)
	return res, nil
}

// CheckAvailability checks availability using MongoDB directly.
func (s *Server) CheckAvailability(ctx context.Context, req *pb.Request) (*pb.Result, error) {
	res := &pb.Result{HotelId: make([]string, 0)}
	for _, hotelId := range req.HotelId {
		available, err := s.isHotelAvailable(ctx, hotelId, req.InDate, req.OutDate, int(req.RoomNumber))
		if err != nil {
			return nil, err
		}
		if available {
			res.HotelId = append(res.HotelId, hotelId)
		}
	}
	return res, nil
}

func (s *Server) isHotelAvailable(ctx context.Context, hotelId string, inDate string, outDate string, roomNumber int) (bool, error) {
	hotelCap, ok, err := getCapacityFromMongo(ctx, s.MongoClient, hotelId)
	if err != nil {
		log.Error().Msgf("Failed get reservation number data for hotelId [%v]: %v", hotelId, err)
		return false, err
	}
	if !ok {
		return false, nil
	}

	available := true
	err = forEachNight(inDate, outDate, func(indate string, outdate string) error {
		count, err := countReservationsFromMongo(ctx, s.MongoClient, hotelId, indate, outdate)
		if err != nil {
			log.Error().Msgf("Failed get reservation data for hotelId [%v] from date [%v] to date [%v]: %v", hotelId, indate, outdate, err)
			return err
		}
		if count+roomNumber > hotelCap {
			available = false
		}
		return nil
	})
	if err != nil {
		return false, err
	}
	return available, nil
}

func forEachNight(inDate string, outDate string, visit func(indate string, outdate string) error) error {
	start, err := time.Parse(time.RFC3339, inDate+"T12:00:00+00:00")
	if err != nil {
		return err
	}
	end, err := time.Parse(time.RFC3339, outDate+"T12:00:00+00:00")
	if err != nil {
		return err
	}

	indate := start.String()[0:10]
	for start.Before(end) {
		start = start.AddDate(0, 0, 1)
		outdate := start.String()[0:10]
		if err := visit(indate, outdate); err != nil {
			return err
		}
		indate = outdate
	}
	return nil
}
